"""Build a clean Windows distribution. Never include live data or the user's Key."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

root=Path(__file__).resolve().parent
source=root/'source' if (root/'source').is_dir() else root
build_output=(root/'build-output').resolve()
work=(root/'build-temp').resolve()
assert build_output.is_relative_to(root) and work.is_relative_to(root)
version_file=root/'windows-version.txt'
version_file.write_text("""VSVersionInfo(ffi=FixedFileInfo(filevers=(1,2,0,0),prodvers=(1,2,0,0),mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('080404b0',[StringStruct('CompanyName',''),StringStruct('FileDescription','西浦课件通本地学习工具'),StringStruct('FileVersion','1.2.0'),StringStruct('InternalName','XJTLUCourseMate'),StringStruct('OriginalFilename','西浦课件通.exe'),StringStruct('ProductName','西浦课件通'),StringStruct('ProductVersion','1.2.0')])]),VarFileInfo([VarStruct('Translation',[2052,1200])])])""",encoding='utf-8')
command=[sys.executable,'-m','PyInstaller','--noconfirm','--windowed','--onedir','--noupx',
         '--name','西浦课件通','--distpath',str(build_output),'--workpath',str(work),'--specpath',str(root),
         '--icon',str(source/'desktop/coursemate.ico'),'--version-file',str(version_file),
         '--collect-submodules','uvicorn','--hidden-import','app.main']
for path,destination in [('static','static'),('sample_data','sample_data'),('app/skill','app/skill'),('desktop','desktop')]:
    command.extend(['--add-data',str(source/path)+';'+destination])
command.append(str(source/'desktop_launcher.py'))
subprocess.run(command,cwd=source,check=True)
bundle=build_output/'西浦课件通'
# Qt uses the unversioned ICU API supplied by Windows 10/11. The build host
# also has a third-party ICU on PATH whose exports are version-suffixed.
# PyInstaller may collect that unrelated DLL; it cannot satisfy Qt's imports.
# Leave Windows' own ICU to the OS loader, rather than redistribute OS DLLs.
for relative in ['_internal/icuuc.dll','_internal/icudt78.dll']:
    target=(bundle/relative).resolve()
    assert target.is_relative_to(bundle.resolve())
    target.unlink(missing_ok=True)
license_dir=bundle/'许可与源代码'
license_dir.mkdir(exist_ok=True)
records=[]
for name in ['PySide6','PySide6_Essentials','PySide6_Addons','PySide6_WebEngine','PySide6_Pdf','shiboken6','PyInstaller','fastapi','starlette','uvicorn','PyMuPDF','requests','certifi','python-multipart']:
    distribution=importlib.metadata.distribution(name)
    records.append({'name':name,'version':distribution.version})
    for file in distribution.files or []:
        normalized=str(file).replace('\\','/')
        if '.dist-info/' in normalized and any(tag in normalized.lower() for tag in ('license','copying','notice')):
            original=Path(distribution.locate_file(file))
            if original.is_file():
                destination=license_dir/name/Path(normalized.split('.dist-info/',1)[1])
                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,destination)
# Readable application source lets recipients inspect the launcher and rebuild it.
code=license_dir/'应用源码';code.mkdir(exist_ok=True)
for path in [source/'desktop_launcher.py',*list((source/'app').rglob('*.py'))]:
    target=code/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
for relative in ['static','sample_data','app/skill','desktop']:
    shutil.copytree(source/relative,code/relative,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
shutil.copy2(Path(__file__),code/'build_app.py')
(code/'requirements.txt').write_text('\n'.join(record['name']+'=='+record['version'] for record in records)+'\n',encoding='utf-8')
if (source/'desktop/licenses').exists():shutil.copytree(source/'desktop/licenses',license_dir/'开源许可',dirs_exist_ok=True)
(license_dir/'组件版本.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
(license_dir/'阅读说明.txt').write_text('第三方组件保留各自许可。Qt 和 PySide 使用 LGPL 开源发行版本；共享库保留为独立文件，可替换后重新运行。\nQt 对应源代码与构建说明：https://download.qt.io/archive/qt/ 和 https://code.qt.io/pyside/pyside-setup.git/ 。\nPyMuPDF 及其底层组件使用其随包附带的开源许可。当前应用源码随包提供；部署版本所用依赖见组件版本.json。\n此处不含个人课件、数据库或 API Key。\n',encoding='utf-8')
(bundle/'先看这里.txt').write_text('西浦课件通 Windows 免安装版 1.2.0\n\n适用 Windows 10（1809 或更新版本）或 Windows 11 的 64 位电脑。\n\n打开方法\n1. 把整个压缩包完整解压到一个普通文件夹。\n2. 双击带紫色图标的 西浦课件通.exe。\n3. 不需要安装 Python，也不需要运行 start 或 demo。\n4. 不要单独移动或发送 exe；_internal 文件夹是随软件提供的运行组件。\n\n第一次使用\n打开设置，选择智谱等服务商，填写你自己的 API Key，先测试再保存。\n没有 Key 时，选择内置离线演示并保存，即可体验上传、双栏预览、助教、总结。演示内容是占位示例，不是真实 AI 翻译。\n真实翻译需要联网；本软件本身不提供共享 API Key。\n\n保存位置\n课程、文件、Key 和设置保存在当前 Windows 账户的 本地应用数据\\XJTLUCourseMate\\data 里。\n软件的 文件 菜单可直接打开这个文件夹。软件升级或重新解压不会清空已保存资料。\n退出软件后资料仍在。卸载软件文件夹也不会自动删除个人学习资料。\n\n常用操作\n左侧加号新建课程 → 上传可选中文字的 PDF → 翻译与逐页讲解自动开始 → 左英右中阅读。\n顶部“课小通AI”打开悬浮助手：滚轮连续查看每页讲解，拖动紫色滑块或使用页码目录定位。可跟随阅读、拖动、调整大小、最小化、放大和关闭。\n课程总概括可选择当前课件或本课程多份课件，沿用辅导分析结构，并可导出 PDF。提问框根据当前页或已选课件答疑。\n关闭悬浮窗不会停止后台分析；退出软件会暂停任务，重开后会续做未完成讲解。已完成内容保存在本地。\n单个 PDF 不超过 80MB；扫描版需先做文字识别。\n右上角“使用说明”、帮助菜单和 F1 均可查看带真实截图的图文教程。\n\n分享\n直接分享干净的压缩包。不要把自己的数据文件夹一起发给别人，里面可能含个人 Key 和课件。\n\n无法启动时\n确认已经完整解压且 _internal 文件夹仍在。\n日志保存在当前账户 本地应用数据\\XJTLUCourseMate\\logs，启动失败时也会显示日志位置。\n若出现系统的来源提示，请先确认文件来自你信任的发送者。\n',encoding='utf-8-sig')
(root/'build-result.json').write_text(json.dumps({'bundle':str(bundle),'launcher':str(bundle/'西浦课件通.exe'),'dependencies':records},ensure_ascii=False,indent=2),encoding='utf-8')
print('Desktop bundle built at',bundle,flush=True)
