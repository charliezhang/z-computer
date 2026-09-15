/**
 * Platform primitives executed by the trusted host (AppFrame), never by app code.
 * The sandboxed iframe has a null origin and no device permissions; it can only ask the host via postMessage.
 */
export async function runPrimitive(name: string, args: any): Promise<unknown> {
  switch (name) {
    case 'takePicture': return takePicture(args);
    case 'recognizeSpeech': return recognizeSpeech(args);
    default: throw new Error(`unknown primitive: ${name}`);
  }
}

/** Captures one JPEG frame from the camera and returns it as a data: URL (max `width` px wide). */
async function takePicture({ width = 640 }: { width?: number } = {}): Promise<string> {
  const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
  try {
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    await video.play();
    await new Promise((r) => setTimeout(r, 600)); // let exposure settle
    const scale = Math.min(1, width / (video.videoWidth || width));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext('2d')!.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.8);
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

/** Listens for one spoken phrase and returns its transcript. */
async function recognizeSpeech({ lang = 'en-US' }: { lang?: string } = {}): Promise<string> {
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!SR) throw new Error('speech recognition is not supported in this browser');
  return new Promise<string>((resolve, reject) => {
    const r = new SR();
    r.lang = lang;
    r.interimResults = false;
    r.maxAlternatives = 1;
    let done = false;
    r.onresult = (e: any) => { done = true; resolve(e.results[0][0].transcript); };
    r.onerror = (e: any) => { done = true; reject(new Error(e.error || 'speech recognition error')); };
    r.onend = () => { if (!done) reject(new Error('no speech heard')); };
    r.start();
  });
}
