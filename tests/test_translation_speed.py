"""Offline regression coverage for translation throughput and failure handling."""
import json
import hashlib
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from app import database, llm, translate_service as service
from app.pdf_utils import extract_blocks, apply_page_translation, normalize_page_rotations


class TranslationTests(unittest.TestCase):
    def setUp(self):
        llm._cooldowns.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.files = self.root / "files"
        self.files.mkdir()
        self.patches = [patch.object(database, "DB_PATH", self.root / "test.db"),
                        patch.object(service, "FILES_DIR", self.files)]
        for item in self.patches:
            item.start()
        database.init_db()
        database.set_settings({"api_base": "http://127.0.0.1:9999/v1",
                               "api_key": "test-only", "model": "mock-llm"})

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_dedup_passthrough_order_progress_and_warm_cache(self):
        texts = ["Database concepts", "42", "Database concepts", "中文", "https://example.com", "Transactions"]
        batches, progress = [], []
        def translate(base, key, model, batch, **kwargs):
            batches.extend(batch)
            return ["译：" + text for text in batch]
        with patch.object(llm, "translate_batch", side_effect=translate) as mock:
            result = service._translate_cached(texts, "http://local/v1", "test", "test",
                                               progress.append)
            self.assertEqual(batches, ["Database concepts", "Transactions"])
            self.assertEqual(result, ["译：Database concepts", "42", "译：Database concepts",
                                      "中文", "https://example.com", "译：Transactions"])
            self.assertEqual(progress, sorted(progress))
            self.assertEqual(progress[-1], len(texts))
            mock.reset_mock()
            self.assertEqual(service._translate_cached(texts, "http://local/v1", "test", "test"), result)
            mock.assert_not_called()

    def test_parallel_out_of_order_results_remain_aligned(self):
        texts = ["First text", "Second text", "Third text", "First text"]
        active, peak, lock = 0, 0, threading.Lock()
        def translate(base, key, model, batch, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(active, peak)
            time.sleep(0.04 if batch[0] == "First text" else 0.01)
            with lock:
                active -= 1
            return ["译：" + text for text in batch]
        with patch.object(llm, "translate_batch", side_effect=translate):
            result = service._translate_cached(texts, "http://local/v1", "test", "parallel",
                                               max_workers=3, batch_chars=12)
        self.assertGreater(peak, 1)
        self.assertEqual(result, ["译：" + text for text in texts])

    def test_provider_failure_is_not_recursively_split(self):
        with patch.object(llm, "translate_batch", side_effect=llm.LLMError("401 invalid credential")) as mock:
            with self.assertRaises(llm.LLMError):
                service._translate_chunk_resilient("http://local/v1", "test", "test", ["a", "b", "c"])
            self.assertEqual(mock.call_count, 1)

    def test_bad_format_is_bounded_and_failed_block_is_not_cached(self):
        def translate(base, key, model, batch, **kwargs):
            if len(batch) > 1 or batch == ["bad"]:
                raise llm.TranslationFormatError("invalid JSON")
            return ["译：" + batch[0]]
        with patch.object(llm, "translate_batch", side_effect=translate):
            with self.assertRaises(llm.LLMError):
                service._translate_cached(["good", "bad"], "http://local/v1", "test", "format")
        with database.db() as conn:
            cached = conn.execute("SELECT hash FROM translation_cache").fetchall()
        self.assertEqual([r[0] for r in cached], [service._hash("format", "good")])

    def _json_reply(self, pairs):
        ids = llm._translation_ids([en for en, _ in pairs])
        return json.dumps({tag: zh for tag, (_, zh) in zip(ids, pairs)})

    def test_glm_payload_keeps_ids_non_thinking_and_json_mode(self):
        with patch.object(llm, "_translation_content", return_value=self._json_reply([('two','乙'),('one','甲')])) as mock:
            result = llm.translate_batch("https://open.bigmodel.cn/api/paas/v4", "test", "glm-4.5-flash",
                                         ["one", "two"], {"min_interval": 2.0})
        self.assertEqual(result, ["甲", "乙"])
        self.assertEqual(mock.call_count, 1)
        for call in mock.call_args_list:
            self.assertEqual(call.kwargs["extra"], {"thinking": {"type": "disabled"}, "response_format":{"type":"json_object"}})
            self.assertGreaterEqual(call.kwargs["max_tokens"], 512)
            self.assertEqual(call.kwargs["min_interval"], 2.0)

    def test_other_providers_do_not_receive_glm_specific_options(self):
        with patch.object(llm, "_translation_content", return_value=self._json_reply([('text','译文')])) as mock:
            llm.translate_batch("https://example.com/v1", "test", "custom", ["text"])
        self.assertNotIn("extra", mock.call_args.kwargs)

    def test_same_length_array_cannot_silently_misalign(self):
        with patch.object(llm,'_translation_content',return_value='["乙", "甲"]') as mock:
            with self.assertRaises(llm.TranslationFormatError):
                llm.translate_batch('http://local','test','test',['one','two'])
        mock.assert_called_once()

    def test_missing_id_retries_only_missing_text_and_keeps_success(self):
        calls=[]
        def translate(base,key,model,batch,**kwargs):
            calls.append(list(batch))
            if len(batch)>1:raise llm.TranslationFormatError('missing one', {0:'甲',2:'丙'})
            return ['乙']
        with patch.object(llm,'translate_batch',side_effect=translate):
            result=service._translate_cached(['one','two','three'],'http://local','test','partial')
        self.assertEqual(result,['甲','乙','丙'])
        self.assertEqual(calls,[['one','two','three'],['two']])

    def test_duplicate_or_foreign_ids_are_rejected(self):
        self.assertIsNone(llm._parse_json_object('{"same":"甲","same":"乙"}'))
        with patch.object(llm,'_translation_content',return_value='{"foreign":"甲"}'):
            with self.assertRaises(llm.TranslationFormatError) as ctx:
                llm.translate_batch('http://local','test','test',['one'])
        self.assertEqual(ctx.exception.partial,{})

    def test_interrupted_json_retains_only_complete_entries(self):
        self.assertEqual(llm._parse_json_object('{"known":"完整译文","missing":"未完',allow_partial=True),{'known':'完整译文'})
        self.assertIsNone(llm._parse_json_object('{"same":"甲","same":"乙"}',allow_partial=True))

    def test_unescaped_quotes_do_not_truncate_translations(self):
        raw='{"taaaaaaaa":"询问"什么信息"，完整句子。","tbbbbbbbb":"第二条。"}'
        parsed=llm._parse_json_object(raw,allow_partial=True,expected_ids=['taaaaaaaa','tbbbbbbbb'])
        self.assertEqual(parsed,{'taaaaaaaa':'询问"什么信息"，完整句子。','tbbbbbbbb':'第二条。'})
        self.assertEqual(llm._parse_json_object('{"id":"前半句"后半句',allow_partial=True),None)

    def test_many_short_labels_are_batched_without_overloading_model(self):
        sizes=[]
        def translate(base,key,model,texts,**kwargs):
            sizes.append(len(texts)); return ['译文：'+text for text in texts]
        with patch.object(llm,'translate_batch',side_effect=translate):
            out=service._translate_cached(['Label '+str(i) for i in range(53)],'http://local','test','labels')
        self.assertEqual(len(out),53)
        self.assertEqual(sizes,[40,13])

    def test_only_exact_slide_labels_use_local_translation(self):
        self.assertEqual(service._local_translation('  In Summary\n'), '总结')
        self.assertEqual(service._local_translation('REFERENCES:'), '参考文献：')
        self.assertEqual(service._local_translation('Learning\nObjectives'), '学习目标')
        self.assertIsNone(service._local_translation('In summary, the system must preserve user access.'))
        self.assertIsNone(service._local_translation('References to external accounts must be validated.'))
        with patch.object(llm, 'translate_batch') as translate:
            result = service._translate_cached(['In Summary', 'References', '42'], 'http://local', 'test', 'labels')
        self.assertEqual(result, ['总结', '参考文献', '42'])
        translate.assert_not_called()

    def test_omitted_items_join_later_batch_and_successes_are_not_regenerated(self):
        texts = ['Label ' + str(index) for index in range(100)]
        calls, progress = [], []
        def translate(base, key, model, items, **kwargs):
            calls.append(list(items))
            if len(calls) == 1:
                raise llm.TranslationFormatError('one missing', {i: '译：' + text for i, text in enumerate(items) if i != 10})
            return ['译：' + text for text in items]
        with patch.object(llm, 'translate_batch', side_effect=translate):
            result = service._translate_cached(texts, 'http://local', 'test', 'merged-retry',
                                               on_progress=progress.append, max_items=64)
        self.assertEqual(result, ['译：' + text for text in texts])
        self.assertEqual([len(items) for items in calls], [64, 37])
        self.assertEqual(calls[1][-1], texts[10])
        self.assertTrue(all(text not in calls[1] for text in calls[0] if text != texts[10]))
        self.assertEqual(progress, [63, 100])

    def test_broken_large_batches_shrink_and_unresolved_items_fail_with_cache(self):
        calls = []
        def translate(base, key, model, items, **kwargs):
            calls.append(list(items))
            if len(items) > 2:
                raise llm.TranslationFormatError('too many entries')
            return ['译：' + text for text in items]
        with patch.object(llm, 'translate_batch', side_effect=translate):
            result = service._translate_cached(['A', 'B', 'C', 'D'], 'http://local', 'test', 'adaptive')
        self.assertEqual(result, ['译：A', '译：B', '译：C', '译：D'])
        self.assertEqual([len(items) for items in calls], [4, 2, 2])

    def test_stream_deadline_closes_connection_and_keeps_completed_text(self):
        class Response:
            closed=False
            def iter_lines(self,**kwargs):
                for text in ('{"id":"中文",','"other":"more"}'):
                    yield 'data: '+json.dumps({'choices':[{'delta':{'content':text}}]})
            def close(self):self.closed=True
        resp=Response()
        with patch.object(llm,'chat',return_value=resp),patch.object(llm.time,'monotonic',side_effect=[0,1,151]):
            content=llm._translation_content('http://local','test','test',[])
        self.assertEqual(llm._parse_json_object(content,allow_partial=True),{'id':'中文'})
        self.assertTrue(resp.closed)

    def test_glm_slot_covers_response_consumption_across_threads(self):
        active, peak, lock = 0,0,threading.Lock()
        class Response:
            def close(self):
                nonlocal active
                with lock:active-=1
        def post(*args,**kwargs):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            return Response()
        def request():
            resp=llm._post('https://open.bigmodel.cn/api/paas/v4/chat/completions','test',json={'model':'glm-4.5-flash'})
            time.sleep(.01)
            resp.close();resp.close()
        with patch.object(llm,'_session') as session:
            session.return_value.post.side_effect=post
            workers=[threading.Thread(target=request) for _ in range(3)]
            for w in workers:w.start()
            for w in workers:w.join()
        self.assertEqual(peak,1)
        self.assertEqual(active,0)

    def test_unvalidated_old_cache_is_not_reused(self):
        old=hashlib.sha256(('test\0one').encode()).hexdigest()
        with database.db() as conn:
            conn.execute('INSERT INTO translation_cache(hash,translated) VALUES(?,?)',(old,'wrong old mapping'))
        with patch.object(llm,'translate_batch',return_value=['正确译文']) as mock:
            self.assertEqual(service._translate_cached(['one'],'http://local','test','test'),['正确译文'])
        mock.assert_called_once()

    def test_years_and_course_identifiers_are_preserved(self):
        for text in ('2026/27S1','IOM205','42','2026-10-17'):
            self.assertFalse(service._needs_translation(text))

    def test_normalization_preserves_rotated_page_appearance(self):
        doc=fitz.open()
        p=doc.new_page(width=300,height=400)
        p.insert_text((60,300),'Group Assignment Workshop',rotate=90,fontsize=15)
        p.draw_rect(fitz.Rect(100,20,150,50),fill=(.1,.3,.7))
        p.set_rotation(90)
        before=p.get_pixmap().samples
        bounds=list(p.rect)
        normalize_page_rotations(doc)
        p=doc[0]
        self.assertEqual(list(p.rect),bounds)
        self.assertEqual(p.rotation,0)
        self.assertEqual(p.get_pixmap().samples,before)
        blocks=extract_blocks(doc)[0]
        self.assertEqual(blocks[0]['rotate'],0)
        apply_page_translation(p,blocks,['小组作业研讨会'])
        for b in p.get_text('dict')['blocks']:
            for line in b.get('lines',[]):
                if any('小组' in s['text'] for s in line['spans']):
                    self.assertEqual(line['dir'],(1,0))
        self.assertIn('小组作业',p.get_text())
        doc.close()

    def test_table_borders_and_fill_survive_redaction(self):
        doc=fitz.open();p=doc.new_page(width=400,height=300)
        p.draw_rect(fitz.Rect(30,30,360,90),fill=(.1,.3,.6))
        p.draw_line((200,30),(200,160),color=(.2,.3,.7),width=2)
        p.insert_text((40,60),'Groupwork: 30% of module mark',color=(1,1,1))
        before=len(p.get_drawings())
        apply_page_translation(p,extract_blocks(doc)[0],['小组作业：占课程总分的30%'])
        self.assertEqual(len(p.get_drawings()),before)
        self.assertIn('30%',p.get_text())
        doc.close()

    def test_table_header_colors_and_cells_remain_separate(self):
        doc=fitz.open();p=doc.new_page(width=500,height=250)
        p.draw_rect(fitz.Rect(20,20,480,60),fill=(.2,.4,.7))
        for x,y,text,color in [(30,45,'Question',(1,1,1)),(230,45,'Attribute clues',(1,1,1)),
                                (30,90,'Who?',(0,0,0)),(230,90,'owner, creator',(0,0,0))]:
            p.insert_text((x,y),text,color=color,fontsize=18)
        blocks=extract_blocks(doc)[0]
        self.assertEqual(len(blocks),4)
        mapping={'Question':'问题','Attribute clues':'属性线索','Who?':'谁？','owner, creator':'所有者、创建者'}
        apply_page_translation(p,blocks,[mapping[b['text']] for b in blocks])
        for b in p.get_text('dict')['blocks']:
            for line in b.get('lines',[]):
                for span in line['spans']:
                    if span['bbox'][1]>60:self.assertEqual(span['color'],0)
        doc.close()

    def test_diagram_labels_on_same_row_do_not_become_a_vertical_list(self):
        doc=fitz.open();p=doc.new_page(width=600,height=150)
        words=['Seller','Publisher','Book','Order']
        for x,word in zip((30,160,310,440),words):p.insert_text((x,70),word,fontsize=16)
        blocks=extract_blocks(doc)[0]
        self.assertEqual(len(blocks),4)
        apply_page_translation(p,blocks,['卖家','出版商','书籍','订单'])
        spans=[s for b in p.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]
        self.assertTrue(all(s['size']>7 for s in spans))
        self.assertLess(max(s['bbox'][1] for s in spans)-min(s['bbox'][1] for s in spans),2)
        doc.close()

    def test_colored_emphasis_does_not_split_one_sentence_into_two_translations(self):
        doc=fitz.open();p=doc.new_page(width=600,height=200)
        p.insert_text((40,70),'No marks will be awarded for the Access-related',fontsize=18,color=(.9,.3,0))
        p.insert_text((40,91),'component if the Access file cannot be opened.',fontsize=18,color=(0,0,0))
        blocks=extract_blocks(doc)[0]
        self.assertEqual(len(blocks),1)
        self.assertIn('cannot be opened',blocks[0]['text'])
        doc.close()

    def test_plain_paragraph_rejoins_separate_pdf_objects(self):
        doc=fitz.open();page=doc.new_page(width=1000,height=400)
        page.insert_text((40,80), 'A university commissions a feasibility study, and the available budget covers a small development team for two', fontsize=12)
        page.insert_text((40,98), 'semesters, with access to the existing student database.', fontsize=12)
        blocks=extract_blocks(doc)[0]
        self.assertEqual(len(blocks),1)
        self.assertIn('two\nsemesters',blocks[0]['text'])
        doc.close()

    def test_bold_continuation_does_not_become_a_second_translation(self):
        doc=fitz.open();page=doc.new_page(width=1000,height=400)
        page.insert_text((40,80), 'When the student opens the schedule page over a mobile connection, the system shall display the schedule', fontsize=12)
        page.insert_text((40,98), 'within 3 seconds', fontsize=12, fontname='hebo')
        blocks=extract_blocks(doc)[0]
        self.assertEqual(len(blocks),1)
        self.assertIn('within 3 seconds',blocks[0]['text'])
        doc.close()

    def test_table_rule_prevents_cross_row_paragraph_merge(self):
        doc=fitz.open();page=doc.new_page(width=1000,height=400)
        page.insert_text((40,80), 'A long table cell describes the available budget and the technical requirements without ending punctuation', fontsize=12)
        page.draw_line((30,85),(950,85))
        page.insert_text((40,98), 'another independent table row begins here', fontsize=12)
        self.assertEqual(len(extract_blocks(doc)[0]),2)
        doc.close()

    def test_policy_preserves_free_tier_limit_and_uses_larger_batches(self):
        glm = service.translation_policy("https://open.bigmodel.cn/api/paas/v4")
        self.assertEqual((glm.max_workers, glm.min_interval), (1, 2.0))
        self.assertEqual(glm.batch_chars, 3600)
        self.assertEqual(glm.max_items, 40)

    def test_fast_translation_is_opt_in_and_stays_on_the_selected_provider(self):
        cfg = {'api_base':'https://open.bigmodel.cn/api/paas/v4', 'model':'glm-4.5-flash'}
        self.assertEqual(service.translation_model(cfg), 'glm-4.5-flash')
        cfg['translation_mode'] = 'fast'
        self.assertEqual(service.translation_model(cfg), 'glm-4-flash-250414')
        cfg['api_base'] = 'https://example.com/v1'
        self.assertEqual(service.translation_model(cfg), 'glm-4.5-flash')
        cfg['api_base'] = 'https://open.bigmodel.cn.attacker.example/v1'
        self.assertEqual(service.translation_model(cfg), 'glm-4.5-flash')
        self.assertEqual(service._hash('glm-4.5-flash','Field') == service._hash('glm-4-flash-250414','Field'), False)

    def test_translation_ids_remain_stable_unique_and_keep_duplicates(self):
        texts = ['Label ' + str(index) for index in range(500)]
        ids = llm._translation_ids(texts)
        self.assertEqual(len(set(ids)), len(texts))
        self.assertTrue(all(len(tag) == 9 for tag in ids))
        self.assertEqual(llm._translation_ids(['same', 'same'])[0], llm._translation_ids(['same', 'same'])[1])
        self.assertEqual(llm._translation_ids(texts), ids)

    def test_dynamic_batches_bound_escaped_payload_and_item_count(self):
        texts = ['Quote " label \\ and newline\n' + str(index) for index in range(200)]
        batches = service._make_batches(texts, batch_chars=1000, max_items=64)
        self.assertEqual([text for chunk in batches for text in chunk], texts)
        self.assertTrue(all(len(chunk) <= 64 for chunk in batches))
        for chunk in batches:
            payload = json.dumps(dict(zip(llm._translation_ids(chunk), chunk)), ensure_ascii=False, separators=(',', ':'))
            self.assertLessEqual(len(payload), 1000)

    def test_ids_preserve_quote_recovery_and_out_of_order_mapping(self):
        ids = llm._translation_ids(['one', 'two'])
        raw = '{"' + ids[1] + '":"第二条","' + ids[0] + '":"带"引号"的第一条"}'
        with patch.object(llm, '_translation_content', return_value=raw):
            result = llm.translate_batch('http://local', 'test', 'test', ['one', 'two'])
        self.assertEqual(result, ['带"引号"的第一条', '第二条'])
        self.assertEqual(service.translation_policy("http://localhost:9999/v1").min_interval, 0)
        self.assertEqual(service.translation_policy("https://example.com/v1").max_workers, 3)

    def test_http_retry_is_bounded_and_releases_responses(self):
        class Response:
            status_code = 429
            closed = False
            def close(self):
                self.closed = True
        responses = [Response() for _ in range(3)]
        with patch.object(llm, "_session") as session, patch.object(llm, "_throttle"), patch.object(llm, "_wait_for_cooldown"):
            session.return_value.post.side_effect = responses
            with self.assertRaises(llm.LLMError):
                llm.chat("http://local/v1", "test", "test", [], max_attempts=3)
        self.assertTrue(all(r.closed for r in responses))
        self.assertEqual(session.return_value.post.call_count, 3)
        self.assertIsInstance(llm._cooldowns[next(iter(llm._cooldowns))][1], int)

    def test_temporary_rate_limit_recovers_full_job_without_manual_retry(self):
        doc_id, original = self._document()
        original_bytes = original.read_bytes()
        observed = []
        clock = [1000.0]
        class Response:
            headers = {}
            def __init__(self, status, body):
                self.status_code, self.body, self.closed = status, body, False
            def json(self): return self.body
            def close(self): self.closed = True
            def iter_lines(self, **kwargs):
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': json.dumps(self.body, ensure_ascii=False)}}]})
                yield 'data: [DONE]'
        responses = []
        def post(url, **kwargs):
            if len(responses) < 3:
                result = Response(429, {'error': {'code': '1302', 'message': '请求过于频繁'}})
            else:
                values = json.loads(kwargs['json']['messages'][-1]['content'])
                result = Response(200, {key: '数据库系统支持业务运营。' for key in values})
            responses.append(result)
            return result
        def sleep(seconds):
            clock[0] += seconds
            with database.db() as conn:
                observed.append(dict(conn.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()))
        with patch.object(llm, '_session') as session, patch.object(llm, '_throttle'), \
             patch.object(llm.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(llm.time, 'sleep', side_effect=sleep), patch('app.course_tutor.start_analysis'):
            session.return_value.post.side_effect = post
            service._run(doc_id)
        with database.db() as conn:
            result = dict(conn.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone())
        self.assertEqual(result['status'], 'done')
        self.assertEqual(result['progress'], 100)
        self.assertEqual(result['retry_at'], 0)
        self.assertEqual(result['status_message'], '')
        self.assertEqual(len(responses), 4)
        self.assertTrue(all(response.closed for response in responses))
        self.assertEqual(clock[0], 1210)
        self.assertTrue(any(row['retry_at'] > 0 and '限流' in row['status_message'] for row in observed))
        self.assertTrue(all(row['status'] == 'translating' and not row['error'] for row in observed))
        self.assertEqual(original.read_bytes(), original_bytes)

    def test_account_quota_errors_do_not_enter_temporary_retry_loop(self):
        class Response:
            status_code = 429
            headers = {}
            def json(self): return {'error': {'code': '1113', 'message': '账户已欠费'}}
            def close(self): pass
        with patch.object(llm, '_session') as session, patch.object(llm, '_throttle'):
            session.return_value.post.return_value = Response()
            with self.assertRaisesRegex(llm.LLMError, '账户已欠费') as caught:
                service._translate_chunk_resilient('http://local/v1', 'test', 'test', ['Hello'])
        self.assertNotIsInstance(caught.exception, llm.RateLimitError)
        self.assertEqual(session.return_value.post.call_count, 1)
        self.assertEqual(llm._cooldowns, {})

    def test_retry_after_and_account_cooldown_are_shared_but_keys_are_isolated(self):
        class Response:
            headers = {'Retry-After': '75'}
            def json(self): return {'error': {'code': '1302', 'message': '限流'}}
        account = llm._account_id('http://local/v1', 'secret', 'model')
        clock = [1000.0]
        waiting = []
        with patch.object(llm.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(llm.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            error = llm._rate_limit(Response(), account)
            self.assertEqual(error.retry_after, 75)
            llm._wait_for_cooldown(llm._account_id('http://local/v1', 'another-key', 'model'), lambda *args: waiting.append(args))
            self.assertFalse(waiting)
            llm._wait_for_cooldown(account, lambda *args: waiting.append(args))
        self.assertEqual(clock[0], 1075)
        self.assertEqual(len(waiting), 1)
        self.assertNotIn('secret', str(account))

    def test_prolonged_cooldown_is_bounded(self):
        account = llm._account_id('http://local/v1', 'test', 'test')
        llm._cooldowns[account] = (time.monotonic() + 5000, 1)
        with self.assertRaisesRegex(llm.LLMError, '15 分钟'):
            llm._wait_for_cooldown(account, deadline=time.monotonic() + 900)

    def test_ssl_eof_and_server_error_recover_without_losing_cached_work(self):
        import requests
        clock = [1000.0]
        attempts, waiting, sent_texts = [], [], []
        service._save_batch(['Cached text'], ['已有译文'], {}, 'test')
        class Response:
            headers = {}
            status_code = 200
            def close(self): pass
            def iter_lines(self, **kwargs):
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': self.content}}]})
                yield 'data: [DONE]'
        class ServerError:
            status_code = 503
            def close(self): pass
        def post(url, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise requests.exceptions.SSLError('UNEXPECTED_EOF_WHILE_READING')
            if len(attempts) == 2:
                return ServerError()
            texts = json.loads(kwargs['json']['messages'][-1]['content'])
            sent_texts.extend(texts.values())
            response = Response()
            response.content = json.dumps({key: '新译文' for key in texts}, ensure_ascii=False)
            return response
        with patch.object(llm, '_session') as session, patch.object(llm, '_throttle'), \
             patch.object(llm.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(llm.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            session.return_value.post.side_effect = post
            result = service._translate_cached(['Cached text', 'New text'], 'http://local/v1', 'test', 'test',
                                                request_options={'on_wait': lambda *args: waiting.append(args)})
        self.assertEqual(result, ['已有译文', '新译文'])
        self.assertEqual(sent_texts, ['New text'])
        self.assertEqual(len(attempts), 3)
        self.assertEqual(clock[0], 1030)
        self.assertTrue(any('连接暂时中断' in message for _, message in waiting))

    def test_certificate_verification_failure_requires_attention(self):
        import requests
        with patch.object(llm, '_session') as session, patch.object(llm, '_throttle'):
            session.return_value.post.side_effect = requests.exceptions.SSLError('CERTIFICATE_VERIFY_FAILED')
            with self.assertRaisesRegex(llm.LLMError, '证书验证失败'):
                service._translate_chunk_resilient('http://local/v1', 'test', 'test', ['Hello'])
        self.assertEqual(session.return_value.post.call_count, 1)
        self.assertFalse(llm._cooldowns)

    def test_sessions_are_reused_per_thread(self):
        main = llm._session()
        self.assertIs(main, llm._session())
        other = []
        thread = threading.Thread(target=lambda: other.append(llm._session()))
        thread.start()
        thread.join()
        self.assertIsNot(main, other[0])
        other[0].close()

    def test_completed_chunked_stream_reuses_actual_http_connection(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import requests
        ports = []
        body = json.dumps({'choices': [{'delta': {'content': '内容' * 400}}]}, ensure_ascii=False)
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args): pass
            def do_POST(self):
                ports.append(self.client_address[1])
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                for data in ('data: ' + body + '\n\n', 'data: [DONE]\n\n'):
                    chunk = data.encode('utf-8')
                    self.wfile.write(f'{len(chunk):X}\r\n'.encode() + chunk + b'\r\n')
                    self.wfile.flush()
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f'http://127.0.0.1:{server.server_port}/v1'
        session = requests.Session()
        session.trust_env = False
        try:
            with patch.object(llm, '_session', return_value=session):
                for _ in range(2):
                    self.assertEqual(llm._translation_content(endpoint, 'test', 'test', [], min_interval=0), '内容' * 400)
            self.assertEqual(ports[0], ports[1])
        finally:
            session.close()
            server.shutdown()
            server.server_close()

    def test_streaming_still_returns_content_and_closes_connection(self):
        class Response:
            closed = False
            def iter_lines(self, **kwargs):
                yield 'data: {"choices":[{"delta":{"content":"你好"}}]}'
                yield 'data: [DONE]'
            def close(self):
                self.closed = True
        response = Response()
        with patch.object(llm, "chat", return_value=response):
            self.assertEqual("".join(llm.chat_stream("http://local", "test", "test", [])), "你好")
        self.assertTrue(response.closed)

    def _document(self):
        with database.db() as conn:
            course = conn.execute("INSERT INTO courses(name) VALUES('Speed regression')").lastrowid
            doc_id = conn.execute("INSERT INTO documents(course_id,filename) VALUES(?,?)",
                                  (course, "source.pdf")).lastrowid
        folder = self.files / str(doc_id)
        folder.mkdir()
        path = folder / "original.pdf"
        pdf = fitz.open()
        for index in range(2):
            page = pdf.new_page(width=400, height=300)
            page.insert_text((40, 70), "Database systems support business operations.")
            page.insert_text((40, 150), str(index + 1))
            page.draw_rect(fitz.Rect(280, 200, 340, 240), fill=(0.2, 0.4, 0.8))
        pdf.save(path)
        pdf.close()
        with database.db() as conn:
            conn.execute("UPDATE documents SET original_path=? WHERE id=?", (str(path), doc_id))
        return doc_id, path

    def test_full_pdf_pipeline_preserves_pages_graphics_and_original(self):
        doc_id, path = self._document()
        original_bytes = path.read_bytes()
        with patch.object(llm, "translate_batch", side_effect=lambda a,b,c,texts,**kw: ["数据库系统支持业务运营。" for _ in texts]), patch("app.course_tutor.start_analysis") as analysis:
            service._run(doc_id)
        with database.db() as conn:
            doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        self.assertEqual(doc["status"], "done")
        self.assertEqual(doc["progress"], 100)
        self.assertEqual(path.read_bytes(), original_bytes)
        before, after = fitz.open(path), fitz.open(doc["translated_path"])
        self.assertEqual(after.page_count, before.page_count)
        for i in range(after.page_count):
            self.assertIn("数据库系统", after[i].get_text())
            self.assertIn(str(i + 1), after[i].get_text())
            rect = fitz.Rect(275,195,345,245)
            self.assertEqual(before[i].get_pixmap(clip=rect).samples, after[i].get_pixmap(clip=rect).samples)
        before.close()
        after.close()
        analysis.assert_called_once_with(doc_id)

    def test_provider_outage_marks_document_failed(self):
        doc_id, _ = self._document()
        with patch.object(llm, "translate_batch", side_effect=llm.LLMError("Service unavailable")), patch("app.course_tutor.start_analysis") as analysis:
            service._run(doc_id)
        with database.db() as conn:
            doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        self.assertEqual(doc["status"], "failed")
        self.assertIn("Service unavailable", doc["error"])
        analysis.assert_not_called()


if __name__ == "__main__":
    unittest.main()
