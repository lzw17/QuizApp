const { request, getUserId } = require('../../utils/request');
const app = getApp();

Page({
  data: {
    bankId: null,
    bankName: '',
    phase: 'prepare',   // prepare | exam
    examCount: 20,
    examMinutes: 30,
    questions: [],
    currentIndex: 0,
    currentQ: null,
    userAnswers: [],    // 索引对应题目，值为选择的答案字符串
    answeredCount: 0,
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
      const list = await request({
        url: `/api/questions?bank_id=${this.data.bankId}&mode=random&limit=${this.data.examCount}`,
      });
      const minutes = Math.max(10, Math.ceil(list.length * 1.5));
      this.setData({
        questions: list,
        userAnswers: new Array(list.length).fill(''),
        currentIndex: 0,
        currentQ: list[0] || null,
        phase: 'exam',
        timeLeft: minutes * 60,
        examMinutes: minutes,
        answeredCount: 0,
      });
      wx.hideLoading();
      this._startTimer();
    } catch {
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
    const unanswered = this.data.questions.length - this.data.answeredCount;
    wx.showModal({
      title: '确认交卷',
      content: unanswered > 0 ? `还有 ${unanswered} 题未作答，确认交卷？` : '确认交卷？',
      confirmText: '交卷',
      success: (res) => { if (res.confirm) this._doSubmit(); },
    });
  },

  async _doSubmit() {
    this._clearTimer();
    wx.showLoading({ title: '评分中...' });
    const uid = await getUserId();
    if (!uid) {
      wx.hideLoading();
      wx.showToast({ title: '登录失败，请重试', icon: 'none' });
      return;
    }
    const answers = this.data.questions.map((q, i) => ({
      question_id: q.id,
      user_answer: this.data.userAnswers[i] || '',
      time_spent: 0,
    }));
    try {
      const result = await request({
        url: '/api/exam/submit',
        method: 'POST',
        data: {
          user_id: uid,
          bank_id: this.data.bankId,
          answers,
          total_time: this.data.examMinutes * 60 - this.data.timeLeft,
        },
      });
      wx.hideLoading();
      // 跳转结果页
      const resultStr = encodeURIComponent(JSON.stringify(result));
      wx.redirectTo({
        url: `/pages/result/result?data=${resultStr}&bank_id=${this.data.bankId}&bank_name=${encodeURIComponent(this.data.bankName)}`,
      });
    } catch {
      wx.hideLoading();
    }
  },

  formatTime(secs) {
    const m = Math.floor(secs / 60).toString().padStart(2, '0');
    const s = (secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  },
});
