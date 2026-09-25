/* ============================================================
 * 语音模块：
 *
 *   按住说话 → 松开
 *     ① MediaRecorder 录制 webm
 *     ② 松开后整段音频交给后端 `/uploads/audio/asr`：后端调 AI 对话层的
 *        本地语音模型转写，**一次调用同时返回文本与 audio_url**
 *     ③ 文本经 onTranscript 填进输入框，考生可自行修改后再发送
 *     ④ 提交答案时直接用 result.url，同一个文件不重复上传
 *
 * 转写失败（引擎未就绪等）由调用方提示考生手动输入，音频仍可在提交时
 * 单独上传——两条路互不阻塞。
 * ============================================================ */

const Voice = {
  // 能力探测（仅在 https 或 localhost 等安全上下文下可用）
  supported: {
    rec: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
  },

  /** 转写文本回调（参数：识别出的完整文本） */
  onTranscript: null,
  /** 录音状态回调（参数：是否正在录音，用于按钮高亮） */
  onStateChange: null,
  /** 错误回调（参数：提示文本） */
  onError: null,

  _recorder: null,
  _stream: null,
  _chunks: [],
  _recording: false,
  _stopResolve: null,
  _stopPromise: null,
  _recSeq: 0,

  /** 最近一次转写的结果：{ text, url, duration_ms, ... }；null = 本轮还没转写 */
  result: null,
  /** 待转写 / 待上传的录音：{ blob, name } */
  pending: null,

  /** 开始（按住说话时调用） */
  start() {
    if (this._recording) return;
    if (!this.supported.rec) {
      this.onError && this.onError("当前浏览器不支持录音，请使用文本输入");
      return;
    }
    this._recording = true;
    this._chunks = [];
    this._stopPromise = null; // transcribe / audioUrl 需等录音真正落盘
    this.pending = null;      // 丢弃上一段未发送的录音，避免错配到本条答案
    this.result = null;       // 上一轮的转写结果同样作废
    this._recSeq += 1;        // 录音代际：旧录音会话的迟到回调按代际丢弃
    this.onStateChange && this.onStateChange(true);

    // 录音：webm/opus，后端支持 mp3/wav/webm/m4a/ogg/aac/flac
    if (this.supported.rec) {
      const recSession = this._recSeq; // 本次录音的代际令牌（与异步回调配对）
      this._stopPromise = new Promise((r) => (this._stopResolve = r));
      (async () => {
        try {
          this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          // 授权弹窗期间用户可能已松手/切走或再次按住（新会话已推进代际）：
          // 复查状态，避免幽灵录音常开麦克风
          if (!this._recording || recSession !== this._recSeq) {
            this._releaseStream();
            this._stopResolve && this._stopResolve();
            return;
          }
          const rec = new MediaRecorder(this._stream);
          rec.ondataavailable = (e) => {
            if (e.data.size) this._chunks.push(e.data);
          };
          rec.onstop = () => {
            this._releaseStream();
            // 旧录音会话的迟到 onstop（用户已再次按住）不写 pending，避免错配录音
            if (recSession === this._recSeq && this._chunks.length) {
              this.pending = {
                blob: new Blob(this._chunks, { type: rec.mimeType || "audio/webm" }),
                name: "answer_" + Date.now() + ".webm",
              };
            }
            this._stopResolve && this._stopResolve();
          };
          this._recorder = rec;
          rec.start();
        } catch (e) {
          this.onError &&
            this.onError(
              "无法使用麦克风：" +
                (e.name === "NotAllowedError" ? "请在浏览器设置中允许麦克风权限" : e.message)
            );
          this._stopResolve && this._stopResolve();
        }
      })();
    }
  },

  /** 停止录音（松开时调用）；转写交给随后的 transcribe() */
  stop() {
    if (!this._recording) return;
    this._recording = false;
    this.onStateChange && this.onStateChange(false);
    try {
      this._recorder && this._recorder.stop();
    } catch (e) {}
  },

  /** 松开后调用：把录音交给后端转写，文本走 onTranscript 回调
   *
   *  结果（含 audio_url）存在 this.result，提交答案时用 audioUrl() 取，
   *  同一个文件不会上传两次。失败时抛错，由调用方提示考生手动输入。
   */
  async transcribe() {
    if (this.result) return this.result; // 同一段录音只转写一次
    if (this._stopPromise) await this._stopPromise;
    if (!this.pending) return null;
    const { blob, name } = this.pending;
    const data = await Api.transcribeAudio(blob, name);
    this.pending = null;
    this.result = data;
    this.onTranscript && this.onTranscript(data.text || "");
    return data;
  },

  /** 提交答案时取音频地址：转写过就复用，否则单独上传（无录音返回 null） */
  async audioUrl() {
    if (this.result && this.result.url) return this.result.url;
    if (this._stopPromise) await this._stopPromise;
    if (!this.pending) return null;
    const { blob, name } = this.pending;
    this.pending = null;
    const data = await Api.uploadAudio(blob, name);
    return data.url;
  },

  _releaseStream() {
    if (this._stream) {
      this._stream.getTracks().forEach((t) => t.stop());
      this._stream = null;
    }
  },
};
