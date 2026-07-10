Page({
  data: {
    result: null,
    wrongItems: [],
    bankId: null,
    typeLabel: { single: '单选', multi: '多选', judge: '判断' },
  },

  onLoad(options) {
    const result = JSON.parse(decodeURIComponent(options.data || '{}'));
    const bankId = parseInt(options.bank_id);

    // 整理错题详情
    const wrongItems = (result.results || [])
      .filter(r => !r.is_correct)
      .map(r => ({
        question_id: r.question_id,
        content: r.content || '',
        type: r.type || 'single',
        user_answer: r.user_answer,
        correct_answer: r.correct_answer,
        explanation: r.explanation,
      }));

    this.setData({ result, wrongItems, bankId });
    wx.setNavigationBarTitle({ title: result.passed ? '考试通过 ✓' : '考试结果' });
  },

  goBack() { wx.navigateBack({ delta: 2 }); },

  reviewWrong() {
    wx.navigateTo({
      url: `/pages/wrong-book/wrong-book?bank_id=${this.data.bankId}`,
    });
  },
});
