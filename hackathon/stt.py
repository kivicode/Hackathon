import queue

import pyaudio
from google.cloud import speech

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms chunks


class ResumableMicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk
        self._buff = queue.Queue()
        self.closed = True
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )
        self.closed = False

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Continuously collect data from the audio stream into the buffer."""
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        """Yields audio chunks from the buffer."""
        while not self.closed:
            # Use a blocking get with a timeout
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Consume whatever other data is in the queue
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b"".join(data)

    def close(self):
        self.closed = True
        self._buff.put(None)
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self._audio_interface.terminate()


def generate_transcripts(stream_generator):
    """
    Consumes the Google API responses and yields finalized text.
    Your main app can loop over this function.
    """
    client = speech.SpeechClient()

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code="en-US",
        enable_automatic_punctuation=True,
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=True,  # Set to False if you only want finalized sentences
    )

    # Convert our local audio generator into Google API requests
    requests = (speech.StreamingRecognizeRequest(audio_content=content) for content in stream_generator)

    responses = client.streaming_recognize(streaming_config, requests)

    for response in responses:
        if not response.results:
            continue

        result = response.results[0]
        if not result.alternatives:
            continue

        transcript = result.alternatives[0].transcript

        # We only yield the finalized sentence to avoid spamming the rest of your app
        # with partial "interim" guesses as the person is speaking.
        if result.is_final:
            yield transcript


# --- How the rest of your app uses this ---
if __name__ == "__main__":
    print("Starting audio stream... (Press Ctrl+C to stop)")
    mic_stream = ResumableMicrophoneStream(RATE, CHUNK)

    try:
        # This creates the stream of text your app needs
        transcript_stream = generate_transcripts(mic_stream.generator())

        # The other part of your app can iterate over this stream like so:
        for final_sentence in transcript_stream:
            print(f"App Received: {final_sentence}")
            # Here is where you would save to a database, send to an LLM, etc.

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        mic_stream.close()
