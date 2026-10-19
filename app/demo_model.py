"""A clearly labelled local demonstration, not an actual language model."""
import json
import time


def reply(messages):
    system=' '.join(str(m.get('content','')) for m in messages if m.get('role')=='system')
    user=' '.join(str(m.get('content','')) for m in messages if m.get('role')=='user')
    if '连接测试' in user:
        return 'OK'
    if 'KXT_PAGE_EXPLANATIONS_V1' in system:
        pages=json.loads(user)
        return json.dumps({key:'# 离线演示 · 本页讲解\n\n> 当前没有调用真实 AI，以下仅用于演示操作流程。\n\n## 这一页在讲什么\n\n请结合本页原文阅读，配置真实 API 后会在这里生成逐项讲解。\n\n## 关键概念\n\n- 术语：保留英文并给出中文说明。\n- 解释：说明原理、关系和使用场景。\n\n## 用例理解\n\n真实模型会在这里提供标注为补充的例子。\n\n## 本页自测\n\n请用自己的话复述这一页的内容。' for key in pages},ensure_ascii=False)
    if 'KXT_COURSE_OVERVIEW_V1' in system:
        return '# 离线演示 · 课程总概括\n\n> 当前未调用真实 AI，仅演示结构与操作流程。\n\n## 课程定位\n\n根据选中的课件组织复习。\n\n## 课件结构总览\n\n- 基础知识\n  - 概念与术语\n  - 方法与案例\n\n## 核心概念详解\n\n### 说人话\n\n配置真实 API 后会生成基于原文的解释。\n\n### 术语对照与重点\n\n保留英文术语，结合原文核实。\n\n## 考点提醒\n\n考点需要以老师要求为准。\n\n## 现实工作应用\n\n真实模型会补充与课件有关的案例。\n\n## 自测题\n\n用自己的话解释本课程的主线。'
    if '翻译引擎' in system:
        values=json.loads(user)
        return json.dumps({key:'演示译文：'+str(value) for key,value in values.items()},ensure_ascii=False)
    if '教务助理' in system or '课程总结' in user:
        return '# 离线演示总结\n\n> 这是本机生成的占位示例，仅用于体验操作流程，不是真实 AI 的课程分析。\n\n## 复习流程\n\n1. 阅读原文与中文对照。\n2. 记录不理解的概念。\n3. 配置自己的模型 API Key，再生成基于课件的正式总结。\n\n## 示例清单\n\n- 核心概念\n- 应用案例\n- 自测问题\n'
    return '# 离线演示模式\n\n当前未调用真实 AI。此内容仅用于体验界面和完整操作流程，不可作为课件答案。\n\n配置自己的 API Key 后，可以围绕课件解释概念、比较术语、举例和生成复习题。'


def chunks(text):
    step=max(8,len(text)//16)
    for start in range(0,len(text),step):
        yield 'data: '+json.dumps({'choices':[{'delta':{'content':text[start:start+step]}}]},ensure_ascii=False)+'\n\n'
        time.sleep(.01)
    yield 'data: [DONE]\n\n'
