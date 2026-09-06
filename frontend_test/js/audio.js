/* ============================================================
 * 语音模块（对照 REPORT_TO_P4 的正确语音流程）：
 *
 *   按住说话 → 松开
 *     ① Web Speech API 语音转写 → 文本填入输入框（可手动修改）
 *     ② MediaRecorder 录制 webm → 点发送时上传 /api/v1/uploads/audio 拿 data.url
 *     ③ 提交答案：answer=转写文本，audio_url=data.url
 *
 * 两项能力相互独立：浏览器不支持转写也能录音上传，反之亦然。
 * ============================================================ */

const Voice = {
  // 能力探测（仅在 https 或 localhost 等安全上下文下可用）
  supported: {
    stt: !!(window.SpeechRecognition || window.webkitSpeechRecognition),
    rec: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
  },

  /** 转写文本回调（参数：识别出的完整文本） */
  onTranscript: null,
  /** 录音状态回调（参数：是否正在录音，用于按钮高亮） */
  onStateChange: null,
  /** 错误回调（参数：提示文本） */
  onError: null,

  _recognition: null,
  _recorder: null,
  _stream: null,
  _chunks: [],
  _finalText: "",
  _recording: false,
  _stopResolve: null,
  _stopPromise: null,

  /** 待上传的录音：{ blob, name }；发送答案前调用 upload() 上传 */
  pending: null,

  /** 开始（按住说话时调用） */
  start() {
    if (this._recording) return;
    if (!this.supported.stt && !this.supported.rec) {
      this.onError && this.onError("当前浏览器不支持语音功能，请使用文本输入");
      return;
    }
    this._recording = true;
    this._finalText = "";
    this._chunks = [];
    this._stopPromise = null; // 仅录音场景创建（upload 需等录音真正落盘）
    this.pending = null; // 丢弃上一段未发送的录音，避免错配到本条答案
    this._session = (this._session || 0) + 1; // 会话代际：迟到转写结果按代际丢弃
    this._recSeq = (this._recSeq || 0) + 1; // 录音代际：旧录音会话的迟到回调按代际丢弃
    this.onStateChange && this.onStateChange(true);

    // ① 语音转写：只取最终识别结果，识别结束后统一回调
    if (this.supported.stt) {
      // 捕获本次会话代际（不能晚到回调里再读 this._session，那会让守卫恒真失效）
      const sttSession = this._session;
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      const rec = new SR();
      rec.lang = "zh-CN";
      rec.continuous = true;
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      rec.onresult = (e) => {
        // 识别引擎在 stop 之后仍会补发迟到结果，按代际丢弃上一段语音的残文
        if (sttSession !== this._session) return;
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) this._finalText += e.results[i][0].transcript;
        }
      };
      rec.onend = () => this._flushTranscript(sttSession);
      rec.onerror = () => {
        // aborted / no-speech 属正常结束，静默处理
      };
      this._recognition = rec;
      try {
        rec.start();
      } catch (e) {
        /* 状态残留时忽略 */
      }
    }

    // ② 录音：webm/opus，后端支持 mp3/wav/webm/m4a/ogg/aac/flac
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

  /** 停止（松开时调用） */
  stop() {
    if (!this._recording) return;
    this._recording = false;
    this.onStateChange && this.onStateChange(false);
    try {
      this._recognition && this._recognition.stop();
    } catch (e) {}
    try {
      this._recorder && this._recorder.stop();
    } catch (e) {}
    // 先把手头已有文本回调出去；识别引擎在 stop 后仍会补发最后一小段 final 结果
    // （说完立刻松手时最后一句话依赖它），给一个短暂窗口让 onend 完成落定，
    // 窗口过后推进代际，此后一切迟到残文被丢弃
    this._flushTranscript(this._session);
    clearTimeout(this._stopTimer);
    this._stopTimer = setTimeout(() => {
      this._flushTranscript(this._session);
      this._session++;
    }, 800);
  },

  /** 上传待传录音，返回音频相对地址（无录音返回 null） */
  async upload() {
    if (this._stopPromise) await this._stopPromise;
    if (!this.pending) return null;
    const { blob, name } = this.pending;
    this.pending = null;
    const data = await Api.uploadAudio(blob, name);
    return data.url;
  },

  _flushTranscript(session) {
    // 代际不匹配 = 上一段语音的迟到结果，丢弃（防止残文混入下一题答案）
    if (session !== this._session) return;
    if (this._finalText) {
      const text = this._finalText;
      this._finalText = "";
      this.onTranscript && this.onTranscript(text);
    }
  },

  _releaseStream() {
    if (this._stream) {
      this._stream.getTracks().forEach((t) => t.stop());
      this._stream = null;
    }
  },
};
