const { request, getUserId } = require('../../utils/request');
const app = getApp();

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
    questions: [],
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

  onLoad(options) {
    this.setData({
      bankId: parseInt(options.bank_id),
      bankName: decodeURIComponent(options.bank_name || ''),
    });
    this._loadTags();
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
    this._clearTimer();
  },

  // ─── 考前准备 ───
  incCount() { if (this.data.examCount < 100) this.setData({ examCount: this.data.examCount + 5 }); },
  decCount() { if (this.data.examCount > 5)  this.setData({ examCount: this.data.examCount - 5 }); },

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
      const minutes = Math.max(10, Math.ceil(list.length * 1.5));
      this.setData({
        questions: list,
        sessionId: exam.session_id,
        userAnswers: new Array(list.length).fill(''),
        currentIndex: 0,
        currentQ: list[0] || null,
        phase: 'exam',
        timeLeft: minutes * 60,
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
    this._timer = setInterval(() => {
      const left = this.data.timeLeft - 1;
      if (left <= 0) {
        this._clearTimer();
        wx.showModal({ title: '时间到！', content: '考试时间已结束，自动交卷', showCancel: false,
          success: () => this._doSubmit(),
        });
      } else {
        this.setData({ timeLeft: left });
      }
    }, 1000);
  },

  _clearTimer() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
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
    if (i >= 0) this.setData({ currentIndex: i, currentQ: this.data.questions[i] });
  },

  nextQ() {
    const i = this.data.currentIndex + 1;
    if (i < this.data.questions.length) this.setData({ currentIndex: i, currentQ: this.data.questions[i] });
  },

  jumpTo(e) {
    const i = e.currentTarget.dataset.index;
    this.setData({ currentIndex: i, currentQ: this.data.questions[i], showSheet: false });
  },

  showSheet() { this.setData({ showSheet: true }); },
  hideSheet() { this.setData({ showSheet: false }); },

  // ─── 交卷 ───
  confirmSubmit() {
    if (this.data.submitting) return;
    const unanswered = this.data.questions.length - this.data.answeredCount;
    wx.showModal({
      title: '确认交卷',
      content: unanswered > 0 ? `还有 ${unanswered} 题未作答，确认交卷？` : '确认交卷？',
      confirmText: '交卷',
      success: (res) => { if (res.confirm) this._doSubmit(); },
    });
  },

  async _doSubmit() {
    if (this.data.submitting || !this.data.sessionId) return;
    this._clearTimer();
    this.setData({ submitting: true });
    wx.showLoading({ title: '评分中...' });
    try {
      const uid = await getUserId();
      if (!uid) {
        wx.showToast({ title: '登录失败，请重试', icon: 'none' });
        return;
      }
      const answers = this.data.questions.map((q, i) => ({
        question_id: q.id,
        user_answer: this.data.userAnswers[i] || '',
        time_spent: 0,
      }));
      const result = await request({
        url: '/api/exam/submit',
        method: 'POST',
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
    } finally {
      this.setData({ submitting: false });
      wx.hideLoading();
    }
  },

  formatTime(secs) {
    const m = Math.floor(secs / 60).toString().padStart(2, '0');
    const s = (secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  },
});
