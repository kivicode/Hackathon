import sounddevice as sd


def list_devices() -> None:
    """List all available audio input and output devices."""
    devices = sd.query_devices()
    print("INPUT devices:")
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            print(f"  [{i}] {d['name']} ({d['max_input_channels']}ch, {int(d['default_samplerate'])}Hz)")
    print("\nOUTPUT devices:")
    for i, d in enumerate(devices):
        if d["max_output_channels"] > 0:
            print(f"  [{i}] {d['name']} ({d['max_output_channels']}ch, {int(d['default_samplerate'])}Hz)")


if __name__ == "__main__":
    list_devices()
