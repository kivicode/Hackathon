import numpy as np
import sounddevice as sd


def find_device_index(device_name: str) -> int:
    """Find the output device index by name."""
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if device_name.lower() in dev["name"].lower() and dev["max_output_channels"] > 0:
            return i
    available = [d["name"] for d in devices if d["max_output_channels"] > 0]
    msg = f"Device '{device_name}' not found. Available output devices: {available}"
    raise ValueError(msg)


def open_stream(device_name: str, sample_rate: int) -> sd.OutputStream:
    """Open a persistent output stream to the specified device."""
    device_index = find_device_index(device_name)
    stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", device=device_index)
    stream.start()
    return stream


def write_chunk(stream: sd.OutputStream, pcm_data: bytes) -> None:
    """Write a chunk of raw PCM bytes to an open stream."""
    audio_array = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
    stream.write(audio_array.reshape(-1, 1))


def play_audio(pcm_data: bytes, device_name: str, sample_rate: int) -> None:
    """Play raw PCM audio bytes to the specified output device (non-streaming)."""
    device_index = find_device_index(device_name)
    audio_array = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio_array, samplerate=sample_rate, device=device_index)
    sd.wait()
