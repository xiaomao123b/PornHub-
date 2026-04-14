import sys
import os
import re
import json
import requests
import subprocess
import shutil
from bs4 import BeautifulSoup
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QComboBox, QProgressBar, QLabel,
    QMessageBox, QFileDialog, QTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class VideoParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://pornhub.com/'
        })

    def parse_video(self, url):
        try:
            response = self.session.get(url, timeout=30)
            response.encoding = 'utf-8'
            html = response.text
            
            video_info = {}
            
            title_match = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()
                if '|' in title:
                    title = title.split('|')[0].strip()
                video_info['title'] = title
            
            flashvars_match = re.search(r'var\s+flashvars_\w+\s*=\s*(\{.*?\});', html, re.DOTALL)
            if flashvars_match:
                try:
                    flashvars = json.loads(flashvars_match.group(1))
                    if 'mediaDefinitions' in flashvars:
                        media_defs = flashvars['mediaDefinitions']
                        resolutions = []
                        for media in media_defs:
                            if isinstance(media, dict):
                                if 'quality' in media and media['quality'] and 'videoUrl' in media:
                                    quality = media['quality']
                                    if isinstance(quality, list):
                                        continue
                                    try:
                                        quality_int = int(quality)
                                        resolutions.append({
                                            'quality': quality_int,
                                            'url': media['videoUrl']
                                        })
                                    except:
                                        pass
                                elif 'quality' in media and media['quality'] and 'video_url' in media:
                                    quality = media['quality']
                                    if isinstance(quality, list):
                                        continue
                                    try:
                                        quality_int = int(quality)
                                        resolutions.append({
                                            'quality': quality_int,
                                            'url': media['video_url']
                                        })
                                    except:
                                        pass
                        if resolutions:
                            video_info['resolutions'] = sorted(resolutions, key=lambda x: x['quality'], reverse=True)
                except Exception as e:
                    pass
            
            if 'resolutions' not in video_info:
                flashvars_match2 = re.search(r'flashvars\s*=\s*(\{.*?\});', html, re.DOTALL)
                if flashvars_match2:
                    try:
                        flashvars = json.loads(flashvars_match2.group(1))
                        if 'mediaDefinitions' in flashvars:
                            media_defs = flashvars['mediaDefinitions']
                            resolutions = []
                            for media in media_defs:
                                if isinstance(media, dict):
                                    if 'quality' in media and 'videoUrl' in media:
                                        resolutions.append({
                                            'quality': media['quality'],
                                            'url': media['videoUrl']
                                        })
                                    elif 'quality' in media and 'video_url' in media:
                                        resolutions.append({
                                            'quality': media['quality'],
                                            'url': media['video_url']
                                        })
                            if resolutions:
                                video_info['resolutions'] = sorted(resolutions, key=lambda x: x['quality'], reverse=True)
                    except Exception as e:
                        pass
            
            if 'resolutions' not in video_info:
                video_urls = re.findall(r'https://[^"]*?\.mp4', html)
                if video_urls:
                    resolutions = []
                    for video_url in video_urls:
                        quality_match = re.search(r'(\d{3,4})p', video_url)
                        if quality_match:
                            quality = int(quality_match.group(1))
                        else:
                            quality = 480
                        resolutions.append({
                            'quality': quality,
                            'url': video_url
                        })
                    if resolutions:
                        video_info['resolutions'] = sorted(resolutions, key=lambda x: x['quality'], reverse=True)
            
            return video_info
        except Exception as e:
            return {'error': str(e)}

class DownloadWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.is_running = True
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Referer': 'https://cn.pornhub.com/'
        }
    
    def stop(self):
        self.is_running = False
    
    def run(self):
        try:
            if self.url.endswith('.m3u8') or 'master.m3u8' in self.url or '.m3u8' in self.url:
                self.download_m3u8()
            else:
                self.download_mp4()
        except Exception as e:
            self.finished.emit(False, str(e))
    
    def get_m3u8_segments(self, m3u8_url):
        try:
            response = requests.get(m3u8_url, headers=self.headers, timeout=30, verify=False)
            content = response.text
        except Exception as e:
            return None, str(e)
        
        base_url = m3u8_url.rsplit('/', 1)[0] + '/'
        
        segments = []
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                if line.startswith('http'):
                    segments.append(line)
                else:
                    segments.append(base_url + line)
        
        return segments, None
    
    def download_m3u8(self):
        self.progress.emit(5)
        
        segments, error = self.get_m3u8_segments(self.url)
        if error:
            self.finished.emit(False, f'获取m3u8文件失败: {error}')
            return
        
        self.progress.emit(10)
        
        if not segments:
            self.finished.emit(False, '未找到视频片段')
            return
        
        first_segment = segments[0]
        if '.m3u8' in first_segment:
            self.url = first_segment
            self.download_m3u8()
            return
        
        ts_urls = [s for s in segments if '.ts' in s or not '.m3u8' in s]
        
        if not ts_urls:
            ts_urls = segments
        
        total_segments = len(ts_urls)
        downloaded_segments = 0
        
        temp_path = self.save_path + '.ts'
        
        with open(temp_path, 'wb') as f:
            for i, ts_url in enumerate(ts_urls):
                if not self.is_running:
                    self.finished.emit(False, '下载已取消')
                    return
                
                retry_count = 0
                max_retries = 3
                while retry_count < max_retries:
                    try:
                        ts_response = requests.get(ts_url, headers=self.headers, timeout=30, verify=False)
                        f.write(ts_response.content)
                        downloaded_segments += 1
                        percentage = int(10 + (downloaded_segments / total_segments) * 85)
                        self.progress.emit(percentage)
                        break
                    except requests.exceptions.SSLError as e:
                        retry_count += 1
                        if retry_count >= max_retries:
                            self.finished.emit(False, f'下载片段失败: {str(e)}')
                            return
                    except Exception as e:
                        self.finished.emit(False, f'下载片段失败: {str(e)}')
                        return
        
        if os.path.exists(self.save_path):
            os.remove(self.save_path)
        os.rename(temp_path, self.save_path)
        
        self.progress.emit(100)
        self.finished.emit(True, self.save_path)
    
    def download_mp4(self):
        response = requests.get(self.url, headers=self.headers, stream=True, timeout=60)
        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0
        
        with open(self.save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if not self.is_running:
                    self.finished.emit(False, '下载已取消')
                    return
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        percentage = int((downloaded_size / total_size) * 100)
                        self.progress.emit(percentage)
        
        self.finished.emit(True, self.save_path)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PornHub 视频下载器')
        self.setGeometry(100, 100, 800, 600)
        
        # 设置窗口图标
        
        self.video_info = None
        self.download_worker = None
        self.batch_urls = []
        self.current_batch_index = 0
        
        self.init_ui()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 设置样式
        central_widget.setStyleSheet('''
            QWidget {
                font-family: Microsoft YaHei;
                font-size: 16px;
                background-color: #f5f5f5;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
            QLineEdit, QTextEdit, QComboBox {
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
                font-size: 16px;
            }
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: #f0f0f0;
                font-size: 16px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 4px;
            }
            QLabel {
                font-weight: 500;
                font-size: 16px;
            }
        ''')
        
        # 模式选择
        mode_layout = QHBoxLayout()
        mode_label = QLabel('下载模式:')
        mode_layout.addWidget(mode_label)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItem('单视频下载', 'single')
        self.mode_combo.addItem('批量下载', 'batch')
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)
        
        # 单视频模式
        self.single_mode = QWidget()
        single_layout = QVBoxLayout(self.single_mode)
        
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('请输入 PornHub 视频链接...')
        self.url_input.setText('https://cn.pornhub.com/view_video.php?viewkey=664b6b1ba2c00')
        url_layout.addWidget(self.url_input)
        
        self.parse_button = QPushButton('解析')
        self.parse_button.clicked.connect(self.parse_video)
        url_layout.addWidget(self.parse_button)
        single_layout.addLayout(url_layout)
        
        title_layout = QHBoxLayout()
        title_label = QLabel('视频标题:')
        title_layout.addWidget(title_label)
        self.title_display = QLabel('')
        self.title_display.setWordWrap(True)
        self.title_display.setStyleSheet('background-color: white; padding: 6px; border-radius: 4px;')
        title_layout.addWidget(self.title_display)
        single_layout.addLayout(title_layout)
        
        resolution_layout = QHBoxLayout()
        resolution_label = QLabel('选择分辨率:')
        resolution_layout.addWidget(resolution_label)
        self.resolution_combo = QComboBox()
        resolution_layout.addWidget(self.resolution_combo)
        single_layout.addLayout(resolution_layout)
        
        layout.addWidget(self.single_mode)
        
        # 批量下载模式
        self.batch_mode = QWidget()
        batch_layout = QVBoxLayout(self.batch_mode)
        
        batch_urls_label = QLabel('批量视频链接 (每行一个):')
        batch_layout.addWidget(batch_urls_label)
        
        self.batch_urls_text = QTextEdit()
        self.batch_urls_text.setPlaceholderText('https://cn.pornhub.com/view_video.php?viewkey=xxx\nhttps://cn.pornhub.com/view_video.php?viewkey=xxx\n...')
        self.batch_urls_text.setMinimumHeight(150)
        batch_layout.addWidget(self.batch_urls_text)
        
        self.start_batch_button = QPushButton('开始批量下载')
        self.start_batch_button.clicked.connect(self.start_batch_download)
        self.start_batch_button.setEnabled(False)
        batch_layout.addWidget(self.start_batch_button)
        
        self.batch_status_label = QLabel('')
        self.batch_status_label.setAlignment(Qt.AlignCenter)
        self.batch_status_label.setStyleSheet('font-weight: bold;')
        batch_layout.addWidget(self.batch_status_label)
        
        layout.addWidget(self.batch_mode)
        self.batch_mode.setVisible(False)
        
        # 公共设置
        path_layout = QHBoxLayout()
        path_label = QLabel('保存路径:')
        path_layout.addWidget(path_label)
        self.path_input = QLineEdit()
        self.path_input.setText(os.path.expanduser('~') + '/Downloads')
        path_layout.addWidget(self.path_input)
        
        self.browse_button = QPushButton('浏览')
        self.browse_button.clicked.connect(self.browse_path)
        path_layout.addWidget(self.browse_button)
        layout.addLayout(path_layout)
        
        self.download_button = QPushButton('下载')
        self.download_button.clicked.connect(self.download_video)
        self.download_button.setEnabled(False)
        layout.addWidget(self.download_button)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel('')
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet('font-weight: 500;')
        layout.addWidget(self.status_label)
        
        log_label = QLabel('操作日志:')
        layout.addWidget(log_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(120)
        self.log_text.setStyleSheet('background-color: white;')
        layout.addWidget(self.log_text)
    
    def on_mode_changed(self, index):
        mode = self.mode_combo.currentData()
        if mode == 'single':
            self.single_mode.setVisible(True)
            self.batch_mode.setVisible(False)
            self.download_button.setEnabled(self.video_info is not None and 'resolutions' in self.video_info)
            self.start_batch_button.setEnabled(False)
        else:
            self.single_mode.setVisible(False)
            self.batch_mode.setVisible(True)
            self.download_button.setEnabled(False)
            self.start_batch_button.setEnabled(True)
    
    def add_log(self, message):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def parse_video(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, '警告', '请输入视频链接')
            return
        
        self.add_log(f'正在解析视频: {url}')
        self.parse_button.setEnabled(False)
        self.download_button.setEnabled(False)
        
        parser = VideoParser()
        self.video_info = parser.parse_video(url)
        
        if 'error' in self.video_info:
            QMessageBox.critical(self, '错误', f'解析失败: {self.video_info["error"]}')
            self.add_log(f'解析失败: {self.video_info["error"]}')
            self.parse_button.setEnabled(True)
            return
        
        if 'title' in self.video_info:
            self.title_display.setText(self.video_info['title'])
            self.add_log(f'视频标题: {self.video_info["title"]}')
        
        if 'resolutions' in self.video_info and len(self.video_info['resolutions']) > 0:
            self.resolution_combo.clear()
            for res in self.video_info['resolutions']:
                self.resolution_combo.addItem(f'{res["quality"]}p', res['url'])
            self.add_log(f'可用分辨率: {[str(r["quality"]) + "p" for r in self.video_info["resolutions"]]}')
            self.download_button.setEnabled(True)
        else:
            QMessageBox.warning(self, '警告', '未找到可用的视频源')
            self.add_log('未找到可用的视频源')
        
        self.parse_button.setEnabled(True)
    
    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, '选择保存目录')
        if path:
            self.path_input.setText(path)
    
    def download_video(self):
        if not self.video_info:
            QMessageBox.warning(self, '警告', '请先解析视频')
            return
        
        selected_index = self.resolution_combo.currentIndex()
        if selected_index < 0:
            QMessageBox.warning(self, '警告', '请选择分辨率')
            return
        
        video_url = self.resolution_combo.itemData(selected_index)
        save_dir = self.path_input.text()
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        
        title = self.video_info.get('title', 'video')
        title = re.sub(r'[\\/:*?"<>|]', '_', title)
        filename = f'{title}.mp4'
        save_path = os.path.join(save_dir, filename)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.download_button.setEnabled(False)
        self.parse_button.setEnabled(False)
        self.status_label.setText('正在下载...')
        
        self.download_worker = DownloadWorker(video_url, save_path)
        self.download_worker.progress.connect(self.update_progress)
        self.download_worker.finished.connect(self.download_finished)
        self.download_worker.start()
        
        self.add_log(f'开始下载: {filename}')
    
    def start_batch_download(self):
        urls_text = self.batch_urls_text.toPlainText().strip()
        if not urls_text:
            QMessageBox.warning(self, '警告', '请输入视频链接')
            return
        
        self.batch_urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
        if not self.batch_urls:
            QMessageBox.warning(self, '警告', '未找到有效的视频链接')
            return
        
        self.current_batch_index = 0
        self.batch_status_label.setText(f'准备开始批量下载 ({len(self.batch_urls)} 个视频)')
        self.start_batch_button.setEnabled(False)
        self.add_log(f'开始批量下载，共 {len(self.batch_urls)} 个视频')
        
        self.process_next_batch_video()
    
    def process_next_batch_video(self):
        if self.current_batch_index >= len(self.batch_urls):
            self.batch_status_label.setText('批量下载完成！')
            self.add_log('批量下载任务全部完成')
            self.start_batch_button.setEnabled(True)
            QMessageBox.information(self, '成功', f'批量下载完成！共下载 {len(self.batch_urls)} 个视频')
            return
        
        url = self.batch_urls[self.current_batch_index]
        self.batch_status_label.setText(f'正在处理视频 {self.current_batch_index + 1}/{len(self.batch_urls)}')
        self.add_log(f'开始处理视频 {self.current_batch_index + 1}: {url}')
        
        parser = VideoParser()
        video_info = parser.parse_video(url)
        
        if 'error' in video_info:
            self.add_log(f'解析失败 {self.current_batch_index + 1}: {video_info["error"]}')
            self.current_batch_index += 1
            self.process_next_batch_video()
            return
        
        if 'resolutions' not in video_info or len(video_info['resolutions']) == 0:
            self.add_log(f'未找到视频源 {self.current_batch_index + 1}')
            self.current_batch_index += 1
            self.process_next_batch_video()
            return
        
        best_resolution = video_info['resolutions'][0]
        video_url = best_resolution['url']
        
        save_dir = self.path_input.text()
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        
        title = video_info.get('title', f'video_{self.current_batch_index + 1}')
        title = re.sub(r'[\\/:*?"<>|]', '_', title)
        filename = f'{title}.mp4'
        save_path = os.path.join(save_dir, filename)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f'正在下载视频 {self.current_batch_index + 1}/{len(self.batch_urls)}')
        
        self.download_worker = DownloadWorker(video_url, save_path)
        self.download_worker.progress.connect(self.update_progress)
        self.download_worker.finished.connect(self.batch_download_finished)
        self.download_worker.start()
    
    def batch_download_finished(self, success, message):
        if success:
            self.add_log(f'视频 {self.current_batch_index + 1} 下载完成: {message}')
        else:
            self.add_log(f'视频 {self.current_batch_index + 1} 下载失败: {message}')
        
        self.current_batch_index += 1
        self.process_next_batch_video()
    
    def update_progress(self, percentage):
        self.progress_bar.setValue(percentage)
        if self.mode_combo.currentData() == 'batch':
            self.status_label.setText(f'正在下载视频 {self.current_batch_index + 1}/{len(self.batch_urls)} - {percentage}%')
        else:
            self.status_label.setText(f'下载进度: {percentage}%')
    
    def download_finished(self, success, message):
        self.progress_bar.setVisible(False)
        
        if success:
            self.status_label.setText('下载完成!')
            self.add_log(f'下载完成: {message}')
            QMessageBox.information(self, '成功', f'视频已下载完成!\n保存位置: {message}')
        else:
            self.status_label.setText('下载失败')
            self.add_log(f'下载失败: {message}')
            QMessageBox.critical(self, '错误', f'下载失败: {message}')
        
        self.download_button.setEnabled(True)
        self.parse_button.setEnabled(True)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())