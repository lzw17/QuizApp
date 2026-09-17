const { request, getUserId } = require('../../utils/request');
const app = getApp();
const AUTO_SUBMIT_MAX_ATTEMPTS = 3;
const AUTO_SUBMIT_RETRY_DELAY_MS = 1500;

Page({
  data: {
    bankId: null,
    bankName: '',
    phase: 'prepare',   // prepare | exam
    examCount: 20,
    examMinutes: 30,
    tags: [],
    selectedTag: '',
    difficulty: null,
    questionIndexes: [],
    questionCount: 0,
    currentIndex: 0,
    currentQ: null,
    userAnswers: [],    // 索引对应题目，值为选择的答案字符串
    sessionId: '',
    answeredCount: 0,
    submitting: false,
    timeLeft: 1800,     // 秒
    showSheet: false,
    typeLabel: { single: '单选', multi: '多选', judge: '判断' },
  },

  _timer: null,
  _questions: [],
  _deadlineMs: 0,
  _autoSubmitTriggered: false,
  _autoSubmitAttempts: 0,
  _autoRetryTimer: null,
  _pageVisible: false,

  onLoad(options) {
    this.setData({
      bankId: parseInt(options.bank_id),
      bankName: decodeURIComponent(options.bank_name || ''),
    });
    this._loadTags();
  },

  onShow() {
    this._pageVisible = true;
    if (this.data.phase === 'exam' && this._deadlineMs && !this.data.submitting) {
      this._startTimer();
    }
  },

  onHide() {
    this._pageVisible = false;
    this._clearTimer();
    this._clearAutoRetry();
  },

  async _loadTags() {
    try {
      const tags = await request({ url: `/api/banks/${this.data.bankId}/tags` });
      this.setData({ tags });
    } catch {}
  },

  setTag(e) {
    this.setData({ selectedTag: e.currentTarget.dataset.tag || '' });
  },

  setDifficulty(e) {
    const value = Number(e.currentTarget.dataset.value);
    this.setData({ difficulty: this.data.difficulty === value ? null : value });
  },

  onUnload() {
    this._pageVisible = false;
    this._clearTimer();
    this._clearAutoRetry();
    this._questions = [];
    this._deadlineMs = 0;
  },

  // ─── 考前准备 ───
  _durationMinutes(count) {
    return Math.ceil(Math.max(10 * 60, count * 90) / 60);
  },

  incCount() {
    if (this.data.examCount >= 100) return;
    const examCount = this.data.examCount + 5;
    this.setData({ examCount, examMinutes: this._durationMinutes(examCount) });
  },

  decCount() {
    if (this.data.examCount <= 5) return;
    const examCount = this.data.examCount - 5;
    this.setData({ examCount, examMinutes: this._durationMinutes(examCount) });
  },

  async startExam() {
    wx.showLoading({ title: '出题中...' });
    try {
      const exam = await request({
        url: '/api/exam/start',
        method: 'POST',
        data: {
          bank_id: this.data.bankId,
          question_count: this.data.examCount,
          tag: this.data.selectedTag || null,
          difficulty: this.data.difficulty,
        },
      });
      const list = exam.questions || [];
      if (!list.length) throw new Error('题库暂无可用题目');
      const durationSeconds = Number(exam.duration_seconds)
        || Math.max(10 * 60, list.length * 90);
      const minutes = Math.ceil(durationSeconds / 60);
      this._questions = list;
      this._deadlineMs = Date.now() + durationSeconds * 1000;
      this._autoSubmitTriggered = false;
      this._autoSubmitAttempts = 0;
      this._clearAutoRetry();
      this.setData({
        questionIndexes: list.map((_, index) => index),
        questionCount: list.length,
        sessionId: exam.session_id,
        userAnswers: new Array(list.length).fill(''),
        currentIndex: 0,
        currentQ: list[0] || null,
        phase: 'exam',
        timeLeft: durationSeconds,
        examMinutes: minutes,
        answeredCount: 0,
      });
      this._startTimer();
    } catch {
    } finally {
      wx.hideLoading();
    }
  },

  _startTimer() {
    this._clearTimer();
    if (!this._syncTimer()) return;
    this._timer = setInterval(() => {
      this._syncTimer();
    }, 1000);
  },

  _syncTimer() {
    if (!this._deadlineMs || this.data.phase !== 'exam') return false;
    const left = Math.max(0, Math.ceil((this._deadlineMs - Date.now()) / 1000));
    if (left !== this.data.timeLeft) this.setData({ timeLeft: left });
    if (left <= 0) {
      this._clearTimer();
      this._handleTimeExpired();
      return false;
    }
    return true;
  },

  _handleTimeExpired() {
    if (this._autoSubmitTriggered || this.data.submitting) return;
    if (this._autoSubmitAttempts >= AUTO_SUBMIT_MAX_ATTEMPTS) return;
    this._autoSubmitAttempts += 1;
    this._autoSubmitTriggered = true;
    if (this._autoSubmitAttempts === 1) {
      wx.showToast({ title: '考试时间已结束，正在自动交卷', icon: 'none' });
    }
    this._doSubmit({ automatic: true });
  },

  _clearTimer() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  },

  _clearAutoRetry() {
    if (this._autoRetryTimer) {
      clearTimeout(this._autoRetryTimer);
      this._autoRetryTimer = null;
    }
  },

  // ─── 答题 ───
  selectOption(e) {
    const key = e.currentTarget.dataset.key;
    const { currentIndex, currentQ, userAnswers } = this.data;
    let ans = userAnswers[currentIndex] || '';

    if (currentQ.type === 'multi') {
      const chars = ans.split('').filter(Boolean);
      const idx = chars.indexOf(key);
      if (idx >= 0) chars.splice(idx, 1); else chars.push(key);
      chars.sort();
      ans = chars.join('');
    } else {
      ans = key;
    }

    const newAnswers = [...userAnswers];
    newAnswers[currentIndex] = ans;
    const answered = newAnswers.filter(Boolean).length;
    this.setData({ userAnswers: newAnswers, answeredCount: answered });
  },

  prevQ() {
    const i = this.data.currentIndex - 1;
    if (i >= 0) this.setData({ currentIndex: i, currentQ: this._questions[i] });
  },

  nextQ() {
    const i = this.data.currentIndex + 1;
    if (i < this._questions.length) this.setData({ currentIndex: i, currentQ: this._questions[i] });
  },

  jumpTo(e) {
    const i = e.currentTarget.dataset.index;
    this.setData({ currentIndex: i, currentQ: this._questions[i], showSheet: false });
  },

  showSheet() { this.setData({ showSheet: true }); },
  hideSheet() { this.setData({ showSheet: false }); },

  // ─── 交卷 ───
  confirmSubmit() {
    if (this.data.submitting) return;
    const unanswered = this.data.questionCount - this.data.answeredCount;
    wx.showModal({
      title: '确认交卷',
      content: unanswered > 0 ? `还有 ${unanswered} 题未作答，确认交卷？` : '确认交卷？',
      confirmText: '交卷',
      success: (res) => { if (res.confirm) this._doSubmit(); },
    });
  },

  async _doSubmit(options = {}) {
    if (this.data.submitting || !this.data.sessionId) return;
    const automatic = options.automatic === true;
    this._clearTimer();
    this._clearAutoRetry();
    this.setData({ submitting: true });
    wx.showLoading({ title: '评分中...' });
    let shouldResumeTimer = false;
    try {
      const uid = await getUserId();
      if (!uid) {
        shouldResumeTimer = true;
        wx.showToast({ title: '登录失败，请重试', icon: 'none' });
        return;
      }
      const answers = this._questions.map((q, i) => ({
        question_id: q.id,
        user_answer: this.data.userAnswers[i] || '',
        time_spent: 0,
      }));
      const result = await request({
        url: '/api/exam/submit',
        method: 'POST',
        silent: true,
        data: {
          session_id: this.data.sessionId,
          bank_id: this.data.bankId,
          answers,
          total_time: this.data.examMinutes * 60 - this.data.timeLeft,
        },
      });
      // 结果写入本地缓存，避免长题干/解析超过小程序页面参数长度限制。
      const resultKey = `exam-result-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      wx.setStorageSync(resultKey, result);
      wx.redirectTo({
        url: `/pages/result/result?result_key=${encodeURIComponent(resultKey)}&bank_id=${this.data.bankId}&bank_name=${encodeURIComponent(this.data.bankName)}`,
      });
    } catch {
      shouldResumeTimer = true;
      if (!automatic || this._autoSubmitAttempts >= AUTO_SUBMIT_MAX_ATTEMPTS) {
        wx.showToast({
          title: automatic ? '自动交卷失败，请点击交卷重试' : '提交失败，请重试',
          icon: 'none',
        });
      }
    } finally {
      this.setData({ submitting: false });
      wx.hideLoading();
      if (shouldResumeTimer && this.data.phase === 'exam') {
        if (this._deadlineMs <= Date.now()) {
          this._autoSubmitTriggered = false;
          if (
            this._pageVisible
            && this._autoSubmitAttempts < AUTO_SUBMIT_MAX_ATTEMPTS
          ) {
            this._autoRetryTimer = setTimeout(() => {
              this._autoRetryTimer = null;
              this._handleTimeExpired();
            }, AUTO_SUBMIT_RETRY_DELAY_MS);
          }
        } else {
          this._startTimer();
        }
      }
    }
  },

  formatTime(secs) {
    const m = Math.floor(secs / 60).toString().padStart(2, '0');
    const s = (secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  },
});
