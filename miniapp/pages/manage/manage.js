const { request } = require('../../utils/request');

Page({
  data: {
    banks: [],
    editingBankId: null,
    editQuestions: [],
    editForm: null,
    statusLabel: { pending: '生成中', ready: '已就绪', reviewing: '审核中' },
    typeLabel: { single: '单选', multi: '多选', judge: '判断' },
  },

  onLoad()  { this._loadBanks(); },
  onShow()  { this._loadBanks(); },

  async _loadBanks() {
    try {
      const list = await request({ url: '/api/banks/all?limit=100' });
      this.setData({ banks: list });
    } catch {}
  },

  async editBank(e) {
    const id = e.currentTarget.dataset.id;
    this.setData({ editingBankId: id });
    try {
      const list = await request({ url: `/api/questions?bank_id=${id}&limit=100` });
      this.setData({ editQuestions: list });
    } catch {}
  },

  closeModal() { this.setData({ editingBankId: null, editQuestions: [] }); },

  showEditForm(e) {
    const q = e.currentTarget.dataset.q;
    this.setData({ editForm: { ...q } });
  },

  closeForm() { this.setData({ editForm: null }); },

  onEditContent(e) { this.setData({ 'editForm.content': e.detail.value }); },
  onEditAnswer(e)  { this.setData({ 'editForm.answer': e.detail.value }); },
  onEditExp(e)     { this.setData({ 'editForm.explanation': e.detail.value }); },

  async saveEdit() {
    const { editForm, editingBankId } = this.data;
    try {
      await request({
        url: `/api/questions/${editForm.id}`,
        method: 'PUT',
        data: {
          bank_id: editingBankId,
          type: editForm.type,
          content: editForm.content,
          options: editForm.options,
          answer: editForm.answer,
          explanation: editForm.explanation,
          tags: editForm.tags,
          difficulty: editForm.difficulty,
        },
      });
      wx.showToast({ title: '保存成功', icon: 'success' });
      this.setData({ editForm: null });
      this.editBank({ currentTarget: { dataset: { id: editingBankId } } });
    } catch {}
  },

  async deleteQuestion(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认删除', content: '删除后不可恢复',
      success: async (res) => {
        if (res.confirm) {
          await request({ url: `/api/questions/${id}`, method: 'DELETE' });
          this.editBank({ currentTarget: { dataset: { id: this.data.editingBankId } } });
        }
      },
    });
  },

  async deleteBank(e) {
    wx.showModal({
      title: '确认删除题库', content: '将删除该题库及所有题目',
      success: async (res) => {
        if (res.confirm) {
          // 简化：直接刷新（后端可扩展删除接口）
          wx.showToast({ title: '功能开发中', icon: 'none' });
        }
      },
    });
  },
});
