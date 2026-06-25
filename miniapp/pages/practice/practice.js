const { request } = require('../../utils/request');
const app = getApp();

Page({
  data: {
    bankId: null,
    mode: 'sequential',
    tag: '',
    questions: [],
    currentIndex: 0,
    question: null,
    total: 0,
    selectedAnswer: '',
    answered: false,
    isCorrect: false,
    correctRate: 0,
    isStarred: false,
    starredIds: [],
    loading: true,
    done: false,
    sessionTotal: 0,
    sessionCorrect: 0,
    isLast: false,
    modeLabel: '',
    typeLabel: { single: '单选', multi: '多选', judge: '判断' },
  },

  _startTime: 0,

  onLoad(options) {
    const { bank_id, mode, tag, skip } = options;
    const modeLabels = { sequential: '顺序练习', random: '随机练习', tag: `「${decodeURIComponent(tag || '')}」`, wrong: '错题复习', starred: '收藏练习' };
    this.setData({
      bankId: parseInt(bank_id),
      mode,
      tag: decodeURIComponent(tag || ''),
      modeLabel: modeLabels[mode] || '练习',
    });
    this._loadQuestions(parseInt(skip) || 0);
    this._loadProgress();
  },

  async _loadQuestions(skip = 0) {
    this.setData({ loading: true });
    try {
      const params = new URLSearchParams({
        bank_id: this.data.bankId,
        mode: this.data.mode === 'tag' ? 'sequential' : this.data.mode,
        skip,
        limit: 50,
      });
      if (this.data.tag) params.append('tag', this.data.tag);
      const list = await request({ url: `/api/questions?${params}` });
      this.setData({
        questions: list,
        total: list.length,
        loading: false,
      });
      if (list.length > 0) {
        this._showQuestion(0);
      } else {
        this.setData({ done: true, loading: false });
      }
    } catch {
      this.setData({ loading: false });
    }
  },

  async _loadProgress() {
    const uid = app.globalData.userId;
    if (!uid) return;
    try {
      const p = await request({ url: `/api/progress/${this.data.bankId}?user_id=${uid}` });
      this.setData({ starredIds: p.starred_ids || [] });
    } catch {}
  },

  _showQuestion(index) {
    const q = this.data.questions[index];
    if (!q) return;
    const isStarred = this.data.starredIds.includes(q.id);
    this.setData({
      currentIndex: index,
      question: q,
      selectedAnswer: '',
      answered: false,
      isCorrect: false,
      isStarred,
      isLast: index === this.data.questions.length - 1,
    });
    this._startTime = Date.now();
  },

  selectOption(e) {
    if (this.data.answered) return;
    const key = e.currentTarget.dataset.key;
    const { question, selectedAnswer } = this.data;

    if (question.type === 'multi') {
      // 多选：toggle
      let ans = selectedAnswer.split('').filter(Boolean);
      const idx = ans.indexOf(key);
      if (idx >= 0) ans.splice(idx, 1);
      else ans.push(key);
      ans.sort();
      this.setData({ selectedAnswer: ans.join('') });
    } else {
      this.setData({ selectedAnswer: key });
    }
  },

  async confirmAnswer() {
    const { question, selectedAnswer, bankId, sessionTotal, sessionCorrect } = this.data;
    if (!selectedAnswer) return;
    const uid = app.globalData.userId;
    const timeSpent = Math.round((Date.now() - this._startTime) / 1000);

    try {
      const result = await request({
        url: '/api/answer',
        method: 'POST',
        data: {
          user_id: uid || 1,
          question_id: question.id,
          bank_id: bankId,
          user_answer: selectedAnswer,
          time_spent: timeSpent,
          mode: this.data.mode === 'wrong' ? 'review' : 'practice',
        },
      });
      this.setData({
        answered: true,
        isCorrect: result.is_correct,
        correctRate: result.correct_rate,
        sessionTotal: sessionTotal + 1,
        sessionCorrect: sessionCorrect + (result.is_correct ? 1 : 0),
      });
      // 顺序模式保存进度
      if (this.data.mode === 'sequential') {
        request({
          url: '/api/progress',
          method: 'POST',
          data: { user_id: uid || 1, bank_id: bankId, position: this.data.currentIndex },
        }).catch(() => {});
      }
    } catch {}
  },

  nextQuestion() {
    const next = this.data.currentIndex + 1;
    if (next >= this.data.questions.length) {
      this.setData({ done: true });
    } else {
      this._showQuestion(next);
    }
  },

  prevQuestion() {
    if (this.data.currentIndex > 0) {
      this._showQuestion(this.data.currentIndex - 1);
    }
  },

  async toggleStar() {
    const uid = app.globalData.userId;
    if (!uid) return;
    try {
      const result = await request({
        url: '/api/star',
        method: 'POST',
        data: { user_id: uid, bank_id: this.data.bankId, question_id: this.data.question.id },
      });
      this.setData({ isStarred: result.is_starred });
      wx.showToast({ title: result.is_starred ? '已收藏' : '已取消收藏', icon: 'none', duration: 1000 });
    } catch {}
  },

  // 辅助：获取选项样式类
  getOptionClass(key) {
    const { answered, selectedAnswer, question } = this.data;
    if (!answered) return selectedAnswer === key ? 'selected' : '';
    const correct = question.answer.toUpperCase();
    const isCorrectKey = correct.includes(key);
    const isSelected = selectedAnswer.toUpperCase().includes(key);
    if (isCorrectKey) return 'correct';
    if (isSelected && !isCorrectKey) return 'wrong';
    return '';
  },

  isCorrectOption(key) {
    return this.data.question?.answer?.toUpperCase().includes(key) || false;
  },

  restart() {
    this.setData({ done: false, sessionTotal: 0, sessionCorrect: 0 });
    this._loadQuestions(0);
  },

  goBack() { wx.navigateBack(); },
});
