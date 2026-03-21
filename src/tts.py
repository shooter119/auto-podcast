from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import edge_tts

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output"


async def _synthesize(text: str, voice: str, rate: str, output_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(output_path))


def generate_audio(script: str, config: dict[str, Any], output_path: Path | None = None) -> Path:
    voice = config["tts"].get("voice", "zh-CN-YunxiNeural")
    rate = config["tts"].get("rate", "+0%")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = output_path or (OUTPUT_DIR / "podcast.mp3")

    logger.info("开始TTS合成 (voice=%s, rate=%s)", voice, rate)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, _synthesize(script, voice, rate, output_path)).result()
        else:
            loop.run_until_complete(_synthesize(script, voice, rate, output_path))
    except RuntimeError:
        asyncio.run(_synthesize(script, voice, rate, output_path))

    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info("音频生成完成: %s (%.1f MB)", output_path.name, size_mb)

    return output_path


def get_audio_duration(audio_path: Path) -> int:
    try:
        from mutagen.mp3 import MP3
        audio = MP3(str(audio_path))
        duration = int(audio.info.length)
        logger.info("音频时长: %d 秒 (%.1f 分钟)", duration, duration / 60)
        return duration
    except Exception:
        logger.warning("无法读取音频时长，返回0")
        return 0
