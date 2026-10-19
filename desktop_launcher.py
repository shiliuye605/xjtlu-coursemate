"""Self-contained Windows desktop entry point. No system Python is used by the build."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
import traceback
from urllib.parse import urlparse

VERSION='1.2.0'
NAME='西浦课件通'
RESOURCE_ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
APP_HOME=Path(os.environ.get('COURSEMATE_HOME',str(Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'XJTLUCourseMate'))).expanduser().resolve()
DATA_HOME=APP_HOME/'data'
LOG_HOME=APP_HOME/'logs'
INSTANCE_FILE=APP_HOME/'instance.json'


def message(text):
    ctypes.windll.user32.MessageBoxW(None,text,NAME,0x10)


def acquire_instance():
    kernel=ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes=[wintypes.LPVOID,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.restype=wintypes.BOOL
    token=hashlib.sha256(str(APP_HOME).casefold().encode()).hexdigest()[:24]
    handle=kernel.CreateMutexW(None,False,'Local\\XJTLUCourseMate-'+token)
    if not handle:raise ctypes.WinError()
    if kernel.GetLastError()!=183:return handle
    # Foreground only the existing application's own window.
    try:
        existing=json.loads(INSTANCE_FILE.read_text(encoding='utf-8'))
        pid=int(existing['pid'])
        user=ctypes.windll.user32
        callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(hwnd,param):
            owner=wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
            if owner.value==pid and user.IsWindowVisible(hwnd):
                user.ShowWindow(hwnd,9);user.SetForegroundWindow(hwnd)
                return False
            return True
        user.EnumWindows(callback(visit),0)
    except Exception:
        message('软件正在启动或已经打开，请稍候查看已有窗口。')
    kernel.CloseHandle(handle)
    return None


def configure_logs():
    LOG_HOME.mkdir(parents=True,exist_ok=True)
    path=LOG_HOME/'desktop.log'
    if path.exists() and path.stat().st_size>3_000_000:
        os.replace(path,LOG_HOME/'desktop.previous.log')
    stream=path.open('a',encoding='utf-8',buffering=1)
    sys.stdout=sys.stderr=stream
    if sys.stdin is None:sys.stdin=open(os.devnull,'r')
    logging.basicConfig(stream=stream,level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',force=True)
    print('\n--- CourseMate '+VERSION+' startup '+time.strftime('%Y-%m-%d %H:%M:%S')+' ---',flush=True)
    return stream


def start_backend():
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    sock.bind(('127.0.0.1',0));sock.listen(2048)
    port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    os.environ['COURSEMATE_DATA_DIR']=str(DATA_HOME)
    os.environ['COURSEMATE_DESKTOP']='1'
    os.environ['COURSEMATE_DEMO_BASE']=base+'/api/demo/v1'
    # This exception is only the application's own loopback traffic.
    for env in ('NO_PROXY','no_proxy'):
        current=os.environ.get(env,'')
        os.environ[env]=','.join(filter(None,[current,'127.0.0.1','localhost']))
    from app.database import init_db,get_settings,set_settings
    init_db()
    cfg=get_settings()
    if not cfg:
        set_settings({'api_base':'https://open.bigmodel.cn/api/paas/v4','model':'glm-4.5-flash','translation_mode':'fast'})
    elif cfg.get('model')=='mock-llm':
        parsed=urlparse(cfg.get('api_base',''))
        if parsed.hostname in ('127.0.0.1','localhost'):
            set_settings({'api_base':os.environ['COURSEMATE_DEMO_BASE'],'api_key':'demo'})
    from app.main import app
    import uvicorn
    config=uvicorn.Config(app,host='127.0.0.1',port=port,log_config=None,access_log=False,loop='asyncio',http='h11',lifespan='on')
    server=uvicorn.Server(config)
    failures=[]
    def run():
        try:server.run(sockets=[sock])
        except BaseException:failures.append(traceback.format_exc());logging.exception('Local service stopped')
    thread=threading.Thread(target=run,name='CourseMate local service',daemon=True)
    thread.start()
    deadline=time.monotonic()+30
    while not server.started:
        if failures or not thread.is_alive():raise RuntimeError(failures[0] if failures else '本地服务未能启动')
        if time.monotonic()>deadline:raise RuntimeError('本地服务启动超时')
        time.sleep(.05)
    return base,server,thread


def run_window(base):
    from PySide6.QtCore import QUrl,QTimer,Qt,QStandardPaths
    from PySide6.QtGui import QAction,QIcon,QDesktopServices,QKeySequence
    from PySide6.QtWidgets import QApplication,QMainWindow,QFileDialog,QMessageBox
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineDownloadRequest
    from app.database import db

    application=QApplication(sys.argv[:1])
    application.setApplicationName(NAME)
    application.setOrganizationName('XJTLUCourseMate')
    application.setApplicationVersion(VERSION)
    application.setWindowIcon(QIcon(str(RESOURCE_ROOT/'desktop/coursemate.ico')))
    application.setStyle('Fusion')
    class LocalPage(QWebEnginePage):
        def acceptNavigationRequest(self,url,kind,is_main_frame):
            if url.toString().startswith(base+'/') or url.scheme() in ('about','data','blob'):
                return True
            if is_main_frame and kind==QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.scheme() in ('https','http'):
                QDesktopServices.openUrl(url)
            return not is_main_frame
        def javaScriptConsoleMessage(self,level,text,line,source):
            if 'RenderingCancelledException' not in text:
                logging.info('Page %s:%s %s',source.split('?')[0],line,text[:700])
    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(NAME)
            self.setMinimumSize(1000,640)
            screen=application.primaryScreen().availableGeometry()
            self.resize(min(1560,screen.width()-60),min(1000,screen.height()-70))
            self.profile=QWebEngineProfile('CourseMate',application)
            self.profile.setPersistentStoragePath(str(APP_HOME/'browser'))
            self.profile.setCachePath(str(APP_HOME/'cache'))
            self.profile.downloadRequested.connect(self.download)
            self.view=QWebEngineView(self)
            self.page=LocalPage(self.profile,self.view)
            self.view.setPage(self.page)
            self.setCentralWidget(self.view)
            self.view.loadFinished.connect(self.loaded)
            self.statusBar().showMessage('Ctrl + R 刷新页面    F1 查看使用说明    文件菜单可打开数据文件夹')
            file_menu=self.menuBar().addMenu('文件')
            file_menu.addAction('打开数据文件夹',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_HOME))))
            file_menu.addAction('打开软件文件夹',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(sys.executable).parent if getattr(sys,'frozen',False) else RESOURCE_ROOT))))
            file_menu.addSeparator();file_menu.addAction('退出',self.close)
            view_menu=self.menuBar().addMenu('查看')
            refresh=QAction('刷新页面',self);refresh.setShortcut(QKeySequence('Ctrl+R'));refresh.triggered.connect(self.view.reload);view_menu.addAction(refresh)
            for label,shortcut,fn in [('放大','Ctrl++',lambda:self.zoom(.1)),('缩小','Ctrl+-',lambda:self.zoom(-.1)),('恢复大小','Ctrl+0',lambda:self.view.setZoomFactor(1))]:
                action=QAction(label,self);action.setShortcut(QKeySequence(shortcut));action.triggered.connect(fn);view_menu.addAction(action)
            help_menu=self.menuBar().addMenu('帮助')
            guide=QAction('使用说明',self);guide.setShortcut(QKeySequence('F1'));guide.triggered.connect(self.guide);help_menu.addAction(guide)
            help_menu.addAction('打开日志文件夹',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_HOME))))
            help_menu.addAction('关于西浦课件通',lambda:QMessageBox.about(self,'关于西浦课件通',f'<h3>西浦课件通 {VERSION}</h3><p>本地课程资料学习工具 Windows 版</p><p>真实 AI 翻译需要使用你自己的 API Key。离线演示只用于体验操作流程。</p><p>第三方组件的许可说明包含在软件目录的 许可与源代码 文件夹。</p>'))
            self.view.setUrl(QUrl(base+'/'))
        def zoom(self,amount):self.view.setZoomFactor(max(.6,min(1.6,self.view.zoomFactor()+amount)))
        def loaded(self,ok):
            if not ok:
                QMessageBox.warning(self,'页面未能打开','本地页面加载失败。可以使用「查看 → 刷新页面」重试，或从「帮助 → 打开日志文件夹」查看启动日志。')
            else:self.statusBar().showMessage('就绪    所有课件和配置保存在当前 Windows 账户    F1 查看使用说明')
        def guide(self):
            self.page.runJavaScript('if(window.openCourseMateGuide)window.openCourseMateGuide();')
        def download(self,request):
            downloads=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            suggested=str(Path(downloads)/Path(request.downloadFileName() or '课程总结.pdf').name)
            if os.environ.get('COURSEMATE_DESKTOP_TESTING')=='1' and os.environ.get('COURSEMATE_TEST_DOWNLOAD_DIR'):
                destination_dir=Path(os.environ['COURSEMATE_TEST_DOWNLOAD_DIR']);destination_dir.mkdir(parents=True,exist_ok=True)
                selected=str(destination_dir/Path(suggested).name)
            else:
                selected,_=QFileDialog.getSaveFileName(self,'保存 PDF',suggested,'PDF 文件 (*.pdf);;所有文件 (*)')
            if not selected:request.cancel();return
            destination=Path(selected)
            request.setDownloadDirectory(str(destination.parent));request.setDownloadFileName(destination.name)
            request.accept()
            self.statusBar().showMessage('正在保存到 '+str(destination),10000)
        def closeEvent(self,event):
            with db() as conn:
                count=conn.execute("SELECT COUNT(*) FROM documents WHERE status IN ('extracting','translating') OR analysis_status='running'").fetchone()[0]
                count+=conn.execute("SELECT COUNT(*) FROM study_pages WHERE status IN ('pending','running')").fetchone()[0]
                count+=conn.execute("SELECT COUNT(*) FROM study_overviews WHERE status IN ('pending','running')").fetchone()[0]
            if count:
                answer=QMessageBox.question(self,'仍有任务进行中','退出软件会暂停后台任务。已完成的讲解保存在本地，下次打开会继续未完成的讲解；中断的翻译可点击重新翻译继续。\n\n确定退出吗？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
            event.accept()
    window=Window();window.show()
    if os.environ.get('COURSEMATE_DESKTOP_TESTING')=='1':
        # Test-only snapshots permit validation of the actual packaged native window.
        def snapshot():window.grab().save(str(APP_HOME/'native-window.png'))
        QTimer.singleShot(4500,snapshot)
        capture_timer=QTimer(window)
        def requested_snapshot():
            trigger=APP_HOME/'capture-request'
            if trigger.exists():
                snapshot();trigger.unlink()
        capture_timer.timeout.connect(requested_snapshot);capture_timer.start(250)
        if os.environ.get('COURSEMATE_TEST_AUTOCLOSE'):
            QTimer.singleShot(int(os.environ['COURSEMATE_TEST_AUTOCLOSE']),application.quit)
    return application.exec()


def main():
    APP_HOME.mkdir(parents=True,exist_ok=True)
    mutex=acquire_instance()
    if mutex is None:return 0
    stream=configure_logs()
    server=thread=None
    try:
        base,server,thread=start_backend()
        INSTANCE_FILE.write_text(json.dumps({'pid':os.getpid(),'url':base,'version':VERSION,'data':str(DATA_HOME)}),encoding='utf-8')
        if os.environ.get('COURSEMATE_DESKTOP_TESTING')=='1' and os.environ.get('COURSEMATE_DEBUG_PORT'):
            os.environ['QTWEBENGINE_REMOTE_DEBUGGING']='127.0.0.1:'+os.environ['COURSEMATE_DEBUG_PORT']
        return run_window(base)
    except BaseException:
        traceback.print_exc()
        message('启动失败，具体原因已写入日志。\n\n日志位置：'+str(LOG_HOME/'desktop.log'))
        return 1
    finally:
        if server:
            server.should_exit=True
            if thread:thread.join(timeout=5)
        try:INSTANCE_FILE.unlink(missing_ok=True)
        except OSError:pass
        ctypes.windll.kernel32.CloseHandle(mutex)
        stream.flush()


if __name__=='__main__':
    raise SystemExit(main())
