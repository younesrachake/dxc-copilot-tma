import { Injectable } from '@angular/core';

/**
 * Text-to-speech via the browser's speechSynthesis (zero backend, offline).
 * Prefers a French voice; falls back to the platform default.
 */
@Injectable({ providedIn: 'root' })
export class TtsService {
  /** id of the message currently being read (null when idle) */
  speakingId: number | null = null;

  get supported(): boolean {
    return typeof window !== 'undefined' && 'speechSynthesis' in window;
  }

  speak(text: string, id: number, onEnd?: () => void): void {
    if (!this.supported) return;
    this.stop();

    // Strip markdown markers and citation indices for natural speech
    const clean = (text || '')
      .replace(/\*\*|__|\*|`/g, '')
      .replace(/\[\d+\]/g, '')
      .replace(/^#{1,4}\s+/gm, '')
      .trim();
    if (!clean) return;

    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.lang = 'fr-FR';
    const voice = speechSynthesis.getVoices().find(v => v.lang.startsWith('fr'));
    if (voice) utterance.voice = voice;
    utterance.rate = 1.05;

    utterance.onend = utterance.onerror = () => {
      this.speakingId = null;
      onEnd?.();
    };

    this.speakingId = id;
    speechSynthesis.speak(utterance);
  }

  stop(): void {
    if (this.supported) speechSynthesis.cancel();
    this.speakingId = null;
  }

  isSpeaking(id: number): boolean {
    return this.speakingId === id;
  }
}
