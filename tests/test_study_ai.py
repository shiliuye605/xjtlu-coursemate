import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app import database,study_ai,llm


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.files=self.root/'files';self.files.mkdir();self.summaries=self.root/'summaries';self.summaries.mkdir()
        self.patches=[patch.object(database,'DB_PATH',self.root/'app.db'),patch.object(study_ai,'FILES_DIR',self.files),patch.object(study_ai,'SUMMARY_DIR',self.summaries)]
        for p in self.patches:p.start()
        database.init_db();database.set_settings({'api_base':'http://test.local/v1','api_key':'test-private-key','model':'test-model'})
        study_ai._blocked_account='';study_ai._blocked_message=''
        study_ai._stop.clear()
        with database.db() as c:c.execute("INSERT INTO courses(id,name) VALUES(1,'Test')")
        self.calls=[]

    def tearDown(self):
        study_ai.stop_workers()
        for thread in [study_ai._worker,study_ai._bootstrap_thread]:
            if thread and thread.is_alive():thread.join(3)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def document(self,pages):
        with database.db() as c:
            doc=c.execute("INSERT INTO documents(course_id,filename,status,page_count) VALUES(1,'test.pdf','done',?)",(len(pages),)).lastrowid
        folder=self.files/str(doc);folder.mkdir()
        path=folder/'text.txt';path.write_text('\n\n'.join(f'【第 {i} 页】\n{text}' for i,text in enumerate(pages,1)),encoding='utf-8')
        with database.db() as c:c.execute('UPDATE documents SET text_path=? WHERE id=?',(str(path),doc))
        study_ai.register_pages(doc,pages);return doc

    def response(self,system,user,output=7000):
        if 'KXT_PAGE_EXPLANATIONS' in system:
            values=json.loads(user);self.calls.append(values)
            return json.dumps({key:'# 本页讲解\n\n完整内容：'+text for key,text in values.items()},ensure_ascii=False)
        return '# 课程总概括\n\n## 课件结构总览\n\n- 测试内容\n\n## 核心概念详解\n\n已覆盖全部选中课件。'

    def test_restart_only_resumes_unfinished_pages(self):
        doc=self.document(['First complete lesson','Second complete lesson','Third complete lesson'])
        claimed=study_ai._claim_pages();study_ai._save_page(claimed[0],'# Already saved\n\nThis page must not be billed twice.')
        with patch.object(study_ai,'_call',side_effect=self.response):
            study_ai.start_workers();deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                with database.db() as c:count=c.execute("SELECT COUNT(*) FROM study_pages WHERE status='done'").fetchone()[0]
                if count==3:break
                time.sleep(.02)
            self.assertEqual(count,3)
            study_ai.stop_workers()
            study_ai._worker.join(5)
            if study_ai._bootstrap_thread:study_ai._bootstrap_thread.join(5)
        self.assertEqual({key for batch in self.calls for key in batch},{'p2','p3'})
        with database.db() as c:self.assertIn('must not be billed twice',c.execute('SELECT markdown FROM study_pages WHERE document_id=? AND page_number=1',(doc,)).fetchone()[0])

    def test_long_page_covers_tail_and_reuses_saved_portions(self):
        text='First topic. '+('Detailed content across the entire page. '*650)+' FINAL_DISTINCT_TOPIC'
        self.document([text]);row=study_ai._claim_pages()[0]
        with patch.object(study_ai,'_call',side_effect=self.response):
            study_ai._run_pages([row]);count=len(self.calls);study_ai._long_page(row)
        self.assertEqual(len(self.calls),count)
        self.assertEqual(''.join(value for call in self.calls for value in call.values()),text)
        with database.db() as c:self.assertIn('FINAL_DISTINCT_TOPIC',c.execute('SELECT markdown FROM study_pages').fetchone()[0])

    def test_invalid_credentials_pause_queue_without_repeated_calls(self):
        self.document([f'Lesson {i} with unique source material' for i in range(8)])
        rows=study_ai._claim_pages()
        with patch.object(study_ai,'_call',side_effect=llm.LLMError('模型服务返回 401: invalid API Key test-private-key')):
            study_ai._run_pages(rows)
        self.assertEqual(study_ai._blocked_account,study_ai._account())
        with database.db() as c:
            errors=[r[0] for r in c.execute("SELECT error FROM study_pages WHERE status='failed'")]
        self.assertFalse(any('test-private-key' in error for error in errors))
        with patch.object(study_ai,'_call') as call:
            study_ai.start_workers();time.sleep(.1);call.assert_not_called()

    def test_late_result_cannot_recreate_deleted_document(self):
        doc=self.document(['First source page with enough content'])
        row=study_ai._claim_pages()[0]
        study_ai.cleanup_overviews([doc])
        with database.db() as c:c.execute('DELETE FROM documents WHERE id=?',(doc,))
        study_ai._save_page(row,'# A response arriving after the user deleted this document')
        with database.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM study_pages').fetchone()[0],0)

    def test_provider_specific_parameters_are_not_sent_to_other_APIs(self):
        self.assertIsNone(study_ai.model_extras({'api_base':'https://api.openai.com/v1','model':'gpt-4o-mini'}))
        self.assertEqual(study_ai.model_extras({'api_base':'https://open.bigmodel.cn/api/paas/v4','model':'glm-4.5-flash'}),{'thinking':{'type':'disabled'}})

    def test_page_response_recovers_unescaped_quotes_without_mixing_IDs(self):
        raw='{"p1":"# 主键\\n\\n解释 \"StudentID\" 的作用。", "p2":"# 规范化\\n\\n完整解释第二页的知识。"}'
        with patch.object(study_ai,'_call',return_value=raw):values=study_ai._page_values({'p1':'First page','p2':'Second page'})
        self.assertIn('StudentID',values['p1']);self.assertIn('第二页',values['p2'])

    def test_structured_values_keep_all_page_content(self):
        raw=json.dumps({'p1':{'主题':'主键与外键','讲解':['完整解释主键。','完整解释外键并给出案例。']}})
        with patch.object(study_ai,'_call',return_value=raw):values=study_ai._page_values({'p1':'Source'})
        self.assertIn('主键',values['p1']);self.assertIn('外键并给出案例',values['p1'])

    def test_upgrade_preserves_existing_analysis_even_if_old_status_is_blank(self):
        doc=self.document(['Existing source page'])
        notes='# 原有辅导分析\n\n保留用户原来的课程笔记，不因旧版状态缺失而重新生成。'
        path=self.files/str(doc)/'analysis.md';path.write_text(notes,encoding='utf-8')
        with database.db() as c:
            c.execute('DELETE FROM study_overviews');c.execute("UPDATE documents SET analysis_status='' WHERE id=?",(doc,))
        row=study_ai.queue_overview(1,[doc],manual=False)
        self.assertEqual(row['origin'],'legacy');self.assertEqual(row['markdown'],notes)
        claimed=study_ai._claim_overview()
        with patch.object(study_ai,'_call') as call:study_ai._run_overview(claimed);call.assert_not_called()
        self.assertEqual(path.read_text(encoding='utf-8'),notes)


if __name__=='__main__':unittest.main()
