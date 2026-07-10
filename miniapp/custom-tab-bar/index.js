Component({
  data: {
    selected: 0,
    color: "#999999",
    selectedColor: "#4F7EFF",
    list: [
      {
        pagePath: "/pages/index/index",
        text: "题库",
        iconPath: "/images/tab/bank.svg",
        selectedIconPath: "/images/tab/bank-active.svg"
      },
      {
        pagePath: "/pages/wrong-book/wrong-book",
        text: "错题本",
        iconPath: "/images/tab/wrong.svg",
        selectedIconPath: "/images/tab/wrong-active.svg"
      },
      {
        pagePath: "/pages/profile/profile",
        text: "我的",
        iconPath: "/images/tab/profile.svg",
        selectedIconPath: "/images/tab/profile-active.svg"
      }
    ]
  },
  methods: {
    switchTab(e) {
      const data = e.currentTarget.dataset
      const url = data.path
      wx.switchTab({ url })
    }
  }
})
