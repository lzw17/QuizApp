const { request, getUserId } = require('../../utils/request');
const app = getApp();

Page({
  data: {
    bankId: null,
    mode: 'sequential',
    source: 'wrong',
    questionId: null,
    isMemorize: false,
    tag: '',
    questions: [],
    currentIndex: 0,
    question: null,
    total: 0,
    selectedAnswer: '',
    correctAnswer: '',
    explanation: '',
    answered: false,
    revealed: false,
    isCorrect: false,
    correctRate: 0,
    isStarred: false,
    starredIds: [],
    loading: true,
    done: false,
    sessionTotal: 0,
    sessionCorrect: 0,
    isLast: false,
    startSkip: 0,
    modeLabel: '',
    typeLabel: { single: '单选', multi: '多选', judge: '判断' },
    userAnswers: {},
    answerSubmitting: false,
    hasMore: false,
    loadingMore: false,
  },

  _startTime: 0,
  _randomSeed: null,
  _reviewCursorId: null,

  onLoad(options) {
    const { bank_id, mode, tag, skip, source, question_id } = options;
    const parsedBankId = parseInt(bank_id, 10);
    const modeLabels = { sequential: '顺序练习', random: '随机练习', tag: `「${decodeURIComponent(tag || '')}」`, wrong: '错题复习', starred: '收藏练习' };
    const startSkip = parseInt(skip) || 0;
    modeLabels.memorize = '背题模式';
    modeLabels.daily = '每日一题';
    this.setData({
      bankId: Number.isFinite(parsedBankId) ? parsedBankId : null,
      mode: mode || 'sequential',
      source: source || 'wrong',
      questionId: question_id ? parseInt(question_id) : null,
      isMemorize: mode === 'memorize',
      tag: decodeURIComponent(tag || ''),
      startSkip,
      modeLabel: modeLabels[mode] || '练习',
    });
    this._randomSeed = mode === 'random'
      ? Math.floor(Math.random() * 2147483647)
      : null;
    this._loadQuestions(startSkip);
    this._loadProgress();
  },

  async _loadQuestions(skip = 0, append = false) {
    if (append && this.data.loadingMore) return;
    const isMutableReview = this.data.mode === 'wrong'
      || this.data.mode === 'starred'
      || this.data.mode === 'memorize';
    if (isMutableReview && !append) this._reviewCursorId = null;
    this.setData(append ? { loadingMore: true } : { loading: true, startSkip: skip });
    try {
      if (this.data.mode === 'memorize') {
        const bankQuery = this.data.bankId ? `&bank_id=${this.data.bankId}` : '';
        const reviewMode = this.data.source === 'starred' ? 'starred' : 'wrong';
        const pageSkip = append ? 0 : skip;
        const cursorQuery = append && this._reviewCursorId !== null
          ? `&after_id=${this._reviewCursorId}`
          : '';
        const [list, countInfo] = await Promise.all([
          request({
            url: `/api/review-questions?source=${reviewMode}${bankQuery}&skip=${pageSkip}&limit=100${cursorQuery}`,
          }),
          append
            ? Promise.resolve({ total: this.data.total })
            : request({
              url: `/api/questions/count?mode=${reviewMode}${bankQuery}`,
            }),
        ]);
        if (list.length) this._reviewCursorId = list[list.length - 1].id;
        const questions = append ? this.data.questions.concat(list) : list;
        const total = Number(countInfo.total || questions.length);
        this.setData({
          questions,
          total,
          hasMore: this.data.startSkip + questions.length < total && list.length > 0,
          loading: false,
          loadingMore: false,
          done: questions.length === 0,
        });
        if (!append && questions.length > 0) this._showQuestion(0);
        return;
      }
      if (this.data.mode === 'daily' && this.data.questionId) {
        const question = await request({ url: `/api/questions/${this.data.questionId}` });
        this.setData({
          questions: [question],
          total: 1,
          hasMore: false,
          loading: false,
          loadingMore: false,
          done: false,
        });
        this._showQuestion(0);
        return;
      }
      const mode = this.data.mode === 'tag' ? 'sequential' : this.data.mode;
      const bankQuery = this.data.bankId ? `bank_id=${this.data.bankId}&` : '';
      const pageSkip = isMutableReview && append ? 0 : skip;
      const cursorQuery = isMutableReview && append && this._reviewCursorId !== null
        ? `&after_id=${this._reviewCursorId}`
        : '';
      let query = `${bankQuery}mode=${mode}&skip=${pageSkip}&limit=100${cursorQuery}`;
      let countQuery = `${bankQuery}mode=${mode}`;
      if (mode === 'random' && this._randomSeed !== null) {
        query += `&seed=${this._randomSeed}`;
      }
      if (mode === 'wrong' || mode === 'starred') {
        const uid = await getUserId();
        if (!uid) {
          wx.showToast({ title: '登录失败，请重试', icon: 'none' });
          this.setData({ loading: false, done: true });
          return;
        }
      }
      if (this.data.tag) {
        query += `&tag=${encodeURIComponent(this.data.tag)}`;
        countQuery += `&tag=${encodeURIComponent(this.data.tag)}`;
      }
      const [list, countInfo] = await Promise.all([
        request({ url: `/api/questions?${query}` }),
        append ? Promise.resolve({ total: this.data.total }) : request({ url: `/api/questions/count?${countQuery}` }),
      ]);
      if (isMutableReview && list.length) {
        this._reviewCursorId = list[list.length - 1].id;
      }
      const questions = append ? this.data.questions.concat(list) : list;
      const total = Number(countInfo.total || questions.length);
      this.setData({
        questions,
        total,
        hasMore: this.data.startSkip + questions.length < total && list.length > 0,
        loading: false,
        loadingMore: false,
      });
      if (questions.length > 0) {
        if (!append) this._showQuestion(0);
      } else {
        this.setData({ done: true, loading: false });
      }
    } catch {
      this.setData({ loading: false, loadingMore: false });
    }
  },

  async _loadProgress() {
    const uid = await getUserId();
    if (!uid) return;
    try {
      if (!this.data.bankId) {
        const starredIds = [];
        const pageSize = 100;
        for (let skip = 0; ; skip += pageSize) {
          const page = await request({
            url: `/api/questions?mode=starred&skip=${skip}&limit=${pageSize}`,
          });
          starredIds.push(...page.map(item => item.id));
          if (page.length < pageSize) break;
        }
        this.setData({
          starredIds,
          isStarred: this.data.question ? starredIds.includes(this.data.question.id) : false,
        });
        return;
      }
      const p = await request({ url: `/api/progress/${this.data.bankId}` });
      const starredIds = p.starred_ids || [];
      this.setData({
        starredIds,
        isStarred: this.data.question ? starredIds.includes(this.data.question.id) : false,
      });
    } catch {}
  },

  _saveCurrentState() {
    const { question, selectedAnswer, answered, isCorrect, correctRate, correctAnswer, explanation, userAnswers } = this.data;
    if (!question) return;
    const updated = Object.assign({}, userAnswers);
    updated[question.id] = { selectedAnswer, answered, revealed: this.data.revealed, isCorrect, correctRate, correctAnswer, explanation };
    this.setData({ userAnswers: updated });
  },

  _showQuestion(index) {
    const q = this.data.questions[index];
    if (!q) return;
    const isStarred = this.data.starredIds.includes(q.id);
    const saved = this.data.userAnswers[q.id];
    this.setData({
      currentIndex: index,
      question: q,
      selectedAnswer: saved ? saved.selectedAnswer : '',
      correctAnswer: saved ? saved.correctAnswer || '' : '',
      explanation: saved ? saved.explanation || '' : '',
      answered: saved ? saved.answered : false,
      revealed: this.data.isMemorize || Boolean(saved && saved.revealed),
      isCorrect: saved ? saved.isCorrect : false,
      correctRate: saved ? saved.correctRate : 0,
      isStarred,
      isLast: index === this.data.questions.length - 1 && !this.data.hasMore,
    });
    if (!saved || !saved.answered) {
      this._startTime = Date.now();
    }
    if (this.data.isMemorize) {
      this.setData({
        answered: true,
        revealed: true,
        correctAnswer: q.answer || '',
        explanation: q.explanation || '',
      });
    }
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
    if (!selectedAnswer || this.data.answerSubmitting) return;
    const questionBankId = question && question.bank_id ? question.bank_id : bankId;
    if (!questionBankId) return;
    const uid = await getUserId();
    if (!uid) {
      wx.showToast({ title: '登录失败，请重试', icon: 'none' });
      return;
    }
    const timeSpent = Math.round((Date.now() - this._startTime) / 1000);

    this.setData({ answerSubmitting: true });
    try {
      const result = await request({
        url: '/api/answer',
        method: 'POST',
        data: {
          question_id: question.id,
          bank_id: questionBankId,
          user_answer: selectedAnswer,
          time_spent: timeSpent,
          mode: this.data.mode === 'wrong' ? 'review' : 'practice',
        },
      });
      this.setData({
        answered: true,
        isCorrect: result.is_correct,
        correctAnswer: result.correct_answer || '',
        explanation: result.explanation || '',
        correctRate: result.correct_rate,
        sessionTotal: sessionTotal + 1,
        sessionCorrect: sessionCorrect + (result.is_correct ? 1 : 0),
      });
      // 顺序模式保存进度
      if (this.data.mode === 'sequential') {
        try {
          await request({
            url: '/api/progress',
            method: 'POST',
            data: { bank_id: questionBankId, position: this.data.startSkip + this.data.currentIndex + 1 },
            silent: true,
          });
        } catch {}
      }
    } catch {} finally {
      this.setData({ answerSubmitting: false });
    }
  },

  async nextQuestion() {
    this._saveCurrentState();
    const next = this.data.currentIndex + 1;
    if (next >= this.data.questions.length) {
      if (this.data.hasMore) {
        await this._loadQuestions(this.data.startSkip + this.data.questions.length, true);
        if (this.data.questions.length > next) this._showQuestion(next);
        else this.setData({ done: true });
      } else {
        this.setData({ done: true });
      }
    } else {
      this._showQuestion(next);
    }
  },

  prevQuestion() {
    if (this.data.currentIndex === 0) return;
    this._saveCurrentState();
    this._showQuestion(this.data.currentIndex - 1);
  },

  async toggleStar() {
    const uid = await getUserId();
    if (!uid) return;
    const questionBankId = this.data.question && this.data.question.bank_id
      ? this.data.question.bank_id
      : this.data.bankId;
    if (!questionBankId) return;
    try {
      const result = await request({
        url: '/api/star',
        method: 'POST',
        data: { bank_id: questionBankId, question_id: this.data.question.id },
      });
      const starredIds = result.is_starred
        ? [...new Set([...this.data.starredIds, this.data.question.id])]
        : this.data.starredIds.filter(id => id !== this.data.question.id);
      this.setData({ isStarred: result.is_starred, starredIds });
      wx.showToast({ title: result.is_starred ? '已收藏' : '已取消收藏', icon: 'none', duration: 1000 });
    } catch {}
  },

  // 辅助：获取选项样式类
  getOptionClass(key) {
    const { answered, selectedAnswer, question } = this.data;
    if (!answered) return selectedAnswer === key ? 'selected' : '';
    const correct = (this.data.correctAnswer || '').toUpperCase();
    const isCorrectKey = correct.includes(key);
    const isSelected = selectedAnswer.toUpperCase().includes(key);
    if (isCorrectKey) return 'correct';
    if (isSelected && !isCorrectKey) return 'wrong';
    return '';
  },

  isCorrectOption(key) {
    return (this.data.correctAnswer || '').toUpperCase().includes(key) || false;
  },

  async restart() {
    if (this.data.mode === 'random') {
      this._randomSeed = Math.floor(Math.random() * 2147483647);
    }
    if (this.data.mode === 'sequential' && this.data.bankId) {
      try {
        await request({
          url: '/api/progress',
          method: 'POST',
          data: { bank_id: this.data.bankId, position: 0, reset: true },
        });
      } catch {
        return;
      }
    }
    this.setData({ done: false, startSkip: 0, sessionTotal: 0, sessionCorrect: 0, userAnswers: {}, correctAnswer: '', explanation: '' });
    await this._loadQuestions(0);
  },

  goBack() { wx.navigateBack(); },
});
