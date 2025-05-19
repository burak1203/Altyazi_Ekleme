import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QLabel, 
                           QVBoxLayout, QWidget, QFileDialog, QProgressBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import speech_recognition as sr
from moviepy.editor import VideoFileClip
from googletrans import Translator
from pydub import AudioSegment
import tempfile
import datetime

class TranslationWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path

    def run(self):
        try:
            temp_dir = tempfile.mkdtemp()
            video = VideoFileClip(self.video_path)
            temp_audio = os.path.join(temp_dir, "temp_audio.wav")
            video.audio.write_audiofile(temp_audio)
            audio = AudioSegment.from_wav(temp_audio)
            recognizer = sr.Recognizer()
            translator = Translator()
            chunk_length = 30 * 1000
            chunks = [audio[i:i + chunk_length] for i in range(0, len(audio), chunk_length)]
            subtitle_blocks = []
            total_chunks = len(chunks)
            block_index = 1
            for i, chunk in enumerate(chunks):
                temp_chunk = os.path.join(temp_dir, f"chunk_{i}.wav")
                chunk.export(temp_chunk, format="wav")
                with sr.AudioFile(temp_chunk) as source:
                    audio_data = recognizer.record(source)
                    result = recognizer.recognize_google(audio_data, language='en-US', show_all=True)
                    if result and 'alternative' in result:
                        best_result = result['alternative'][0]
                        if 'transcript' in best_result:
                            transcript = best_result['transcript']
                            translation = translator.translate(transcript, dest='tr').text
                            # Eğer zaman damgaları varsa kullan
                            if 'timestamps' in best_result:
                                timestamps = best_result['timestamps']
                                # Her kelime için (kelime, start, end) var
                                kelimeler = translation.split()
                                orijinal_kelimeler = transcript.split()
                                # Zaman damgalarını orijinal kelimelerden alacağız
                                idx = 0
                                while idx < len(orijinal_kelimeler):
                                    block_words = []
                                    block_start = timestamps[idx][1]
                                    # 10-20 kelime arası blok oluştur
                                    for j in range(10):
                                        if idx < len(orijinal_kelimeler):
                                            block_words.append(kelimeler[idx] if idx < len(kelimeler) else orijinal_kelimeler[idx])
                                            idx += 1
                                    # 20'ye kadar kelime ekle (maksimum 20)
                                    while len(block_words) < 20 and idx < len(orijinal_kelimeler):
                                        block_words.append(kelimeler[idx] if idx < len(kelimeler) else orijinal_kelimeler[idx])
                                        idx += 1
                                    block_end = timestamps[idx-1][2]
                                    # SRT bloğu oluştur
                                    subtitle_blocks.append(
                                        f"{block_index}\n"
                                        f"{self.format_time(block_start)} --> {self.format_time(block_end)}\n"
                                        f"{' '.join(block_words)}\n"
                                    )
                                    block_index += 1
                            else:
                                # Zaman damgası yoksa, chunk'ın başı ve sonunu kullan
                                block_start = i * 30
                                block_end = block_start + 30
                                kelimeler = translation.split()
                                idx = 0
                                while idx < len(kelimeler):
                                    block_words = kelimeler[idx:idx+20]
                                    subtitle_blocks.append(
                                        f"{block_index}\n"
                                        f"{self.format_time(block_start)} --> {self.format_time(block_end)}\n"
                                        f"{' '.join(block_words)}\n"
                                    )
                                    block_index += 1
                                    idx += 20
                progress = int((i + 1) / total_chunks * 100)
                self.progress.emit(progress)
            output_path = os.path.splitext(self.video_path)[0] + ".srt"
            with open(output_path, "w", encoding="utf-8") as f:
                for block in subtitle_blocks:
                    f.write(block + "\n")
            for file in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, file))
            os.rmdir(temp_dir)
            self.finished.emit(f"Altyazı dosyası oluşturuldu: {output_path}")
        except Exception as e:
            self.error.emit(str(e))

    def format_time(self, seconds):
        time = datetime.timedelta(seconds=seconds)
        total_seconds = int(time.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Ses Çevirici")
        self.setMinimumSize(600, 400)
        
        # Ana widget ve layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Dosya seçme butonu
        self.select_button = QPushButton("Video Seç")
        self.select_button.clicked.connect(self.select_video)
        layout.addWidget(self.select_button)
        
        # Seçilen dosya etiketi
        self.file_label = QLabel("Henüz dosya seçilmedi")
        layout.addWidget(self.file_label)
        
        # İlerleme çubuğu
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Çeviri sonucu etiketi
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setAlignment(Qt.AlignTop)
        layout.addWidget(self.result_label)
        
        self.video_path = None
        self.worker = None

    def select_video(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Video Seç",
            "",
            "Video Dosyaları (*.mp4 *.avi *.mkv)"
        )
        
        if file_name:
            self.video_path = file_name
            self.file_label.setText(f"Seçilen dosya: {os.path.basename(file_name)}")
            self.start_translation()

    def start_translation(self):
        if not self.video_path:
            return
            
        self.select_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.result_label.setText("Çeviri başlatılıyor...")
        
        self.worker = TranslationWorker(self.video_path)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.translation_finished)
        self.worker.error.connect(self.translation_error)
        self.worker.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def translation_finished(self, result):
        self.result_label.setText(result)
        self.select_button.setEnabled(True)
        self.progress_bar.setVisible(False)

    def translation_error(self, error_message):
        self.result_label.setText(f"Hata oluştu: {error_message}")
        self.select_button.setEnabled(True)
        self.progress_bar.setVisible(False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_()) 