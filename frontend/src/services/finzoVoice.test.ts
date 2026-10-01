/**
 * Microphone permission handling and single-playback guarantees.
 * Browser APIs are stubbed: no real device is touched.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswerPlayer, MicError, PushToTalkRecorder, toMicError } from "./finzoVoice";

function stubBrowser(getUserMedia: () => Promise<MediaStream>, secure = true) {
  vi.stubGlobal("window", { isSecureContext: secure, setTimeout, clearTimeout });
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  vi.stubGlobal("MediaRecorder", class { static isTypeSupported() { return true; } });
}

afterEach(() => vi.unstubAllGlobals());

describe("microphone permission failures", () => {
  it.each([
    ["NotAllowedError", "denied", /blocked/],
    ["SecurityError", "denied", /blocked/],
    ["NotFoundError", "no-device", /No microphone/],
    ["NotReadableError", "busy", /another app/],
  ])("%s becomes a %s error the user can act on", (name, kind, message) => {
    const err = toMicError(new DOMException("x", name));
    expect(err).toBeInstanceOf(MicError);
    expect(err.kind).toBe(kind);
    expect(err.message).toMatch(message);
  });

  it("start() rejects with a friendly error when permission is denied", async () => {
    stubBrowser(() => Promise.reject(new DOMException("denied", "NotAllowedError")));
    const rec = new PushToTalkRecorder();
    await expect(rec.start()).rejects.toMatchObject({ kind: "denied" });
  });

  it("refuses on an insecure page before prompting", async () => {
    const getUserMedia = vi.fn();
    stubBrowser(getUserMedia, false);
    await expect(new PushToTalkRecorder().start()).rejects.toMatchObject({ kind: "insecure" });
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("reports unsupported browsers", async () => {
    vi.stubGlobal("window", { isSecureContext: true });
    vi.stubGlobal("navigator", {});
    await expect(new PushToTalkRecorder().start()).rejects.toMatchObject({ kind: "unsupported" });
  });

  it("never leaks a raw DOMException message", () => {
    const err = toMicError(new Error("NS_ERROR_WEIRD internal stack"));
    expect(err.kind).toBe("unknown");
    expect(err.message).not.toMatch(/NS_ERROR/);
  });
});

describe("answer playback", () => {
  it("stopping the current answer before playing the next one", async () => {
    const played: string[] = [];
    let pauses = 0;
    class FakeAudio {
      src = "";
      currentTime = 0;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      play() {
        played.push(this.src);
        return Promise.resolve();
      }
      pause() {
        pauses += 1;
      }
    }
    vi.stubGlobal("Audio", FakeAudio);
    vi.stubGlobal("window", {});
    const player = new AnswerPlayer();
    const first = player.play("AAA", "audio/wav");
    void player.play("BBB", null);
    await first; // the first answer resolves as soon as the second starts
    expect(played).toEqual(["data:audio/wav;base64,AAA", "data:audio/mpeg;base64,BBB"]);
    // Exactly one pause: the first answer, stopped before the second began.
    expect(pauses).toBe(1);
  });
});
