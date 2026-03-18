"""
Non-blocking audio alert service using pre-recorded WAV files.
"""

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 오디오 파일 이름 상수
_AUDIO_NO_HELMET = "no_helmet.wav"
_AUDIO_NO_JACKET = "no_jacket.wav"
_AUDIO_NO_BOTH = "no_helmet_no_jacket.wav"


class AudioService:
    """사전 녹음된 WAV 파일을 비차단 방식으로 재생하는 서비스.

    simpleaudio를 사용하여 낮은 지연으로 WAV를 재생한다.
    동시에 여러 알림이 트리거되어도 재생이 겹치지 않도록 제어한다.

    SRP: 이 클래스는 오직 오디오 재생 책임만 담당한다.
    """

    def __init__(self, audio_dir: Path) -> None:
        """
        Args:
            audio_dir: WAV 파일이 위치한 디렉터리 경로
        """
        self._audio_dir = audio_dir
        self._is_playing = False
        self._play_lock = threading.Lock()

        # simpleaudio WaveObject 사전 로드 (서버 시작 시 1회)
        self._waves: dict[str, object] = {}
        self._load_waves()

    def _load_waves(self) -> None:
        """WAV 파일을 메모리에 사전 로드한다.

        파일이 없으면 경고 로그를 남기고 해당 키를 None으로 설정한다.
        """
        try:
            import simpleaudio as sa

            self._sa = sa
        except ImportError:
            logger.warning("simpleaudio를 찾을 수 없습니다. 오디오 알림이 비활성화됩니다. 설치: pip install simpleaudio")
            self._sa = None
            return

        for filename in [_AUDIO_NO_HELMET, _AUDIO_NO_JACKET, _AUDIO_NO_BOTH]:
            path = self._audio_dir / filename
            if path.exists():
                try:
                    self._waves[filename] = sa.WaveObject.from_wave_file(str(path))
                    logger.info(f"오디오 파일 로드: {path}")
                except Exception as e:
                    logger.warning(f"오디오 파일 로드 실패 ({path}): {e}")
                    self._waves[filename] = None
            else:
                logger.warning(f"오디오 파일 없음: {path}")
                self._waves[filename] = None

    def play_non_blocking(self, missing_helmet: bool, missing_jacket: bool) -> None:
        """미착용 항목에 해당하는 알림음을 비차단 방식으로 재생한다.

        현재 재생 중인 경우 새 요청을 무시하여 알림음이 겹치지 않도록 한다.

        Args:
            missing_helmet: 안전모 미착용 여부
            missing_jacket: 안전 조끼 미착용 여부
        """
        if self._sa is None:
            return

        with self._play_lock:
            if self._is_playing:
                return
            self._is_playing = True

        # 재생할 파일 선택
        if missing_helmet and missing_jacket:
            filename = _AUDIO_NO_BOTH
        elif missing_helmet:
            filename = _AUDIO_NO_HELMET
        else:
            filename = _AUDIO_NO_JACKET

        wave_obj = self._waves.get(filename)
        if wave_obj is None:
            logger.warning(f"재생할 오디오 파일이 없습니다: {filename}")
            with self._play_lock:
                self._is_playing = False
            return

        # 별도 스레드에서 재생 (감지 루프 블로킹 방지)
        threading.Thread(
            target=self._play_and_reset,
            args=(wave_obj,),
            daemon=True,
        ).start()

    def _play_and_reset(self, wave_obj: object) -> None:
        """WAV를 재생하고 완료 후 재생 플래그를 초기화한다."""
        try:
            play_obj = wave_obj.play()
            play_obj.wait_done()  # 재생 완료까지 이 스레드만 블로킹
        except Exception as e:
            logger.warning(f"오디오 재생 중 오류: {e}")
        finally:
            with self._play_lock:
                self._is_playing = False
