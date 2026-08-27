"""
Convert Arabic text to speech using Groq Orpheus.
Source: https://console.groq.com/docs/text-to-speech/orpheus
"""

import os
import base64
from groq import Groq
from dotenv import load_dotenv

load_dotenv()


class AnnaqTTS:
    def __init__(self):
        self.client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        self.model = "canopylabs/orpheus-arabic-saudi"
        self.voice = "aisha"

    def get_audio_base64(self, text):
        if not text:
            return ""

        # remove ** from markdown so TTS does not say "asterisk"
        text = text.replace("**", "")

        try:
            response = self.client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="wav",
            )
            response.write_to_file("temp.wav")

            with open("temp.wav", "rb") as f:
                audio_bytes = f.read()
            os.remove("temp.wav")

            return base64.b64encode(audio_bytes).decode("utf-8")

        except Exception as e:
            print(f"TTS failed: {e}")
            return ""


# test the module from command line
if __name__ == "__main__":
    import pygame

    tts = AnnaqTTS()
    text = input("Enter Arabic text: ")
    audio_b64 = tts.get_audio_base64(text)

    if audio_b64:
        with open("output.wav", "wb") as f:
            f.write(base64.b64decode(audio_b64))

        pygame.mixer.init()
        pygame.mixer.music.load("output.wav")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)

        os.remove("output.wav")
