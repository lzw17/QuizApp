'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadPage(relativePath, mocks) {
  const filename = path.join(__dirname, '..', relativePath);
  const source = fs.readFileSync(filename, 'utf8');
  let definition = null;
  const sandbox = {
    console,
    clearTimeout,
    setTimeout,
    getApp: () => mocks.app || {},
    Page: page => { definition = page; },
    wx: mocks.wx || {},
    require: request => {
      if (request === '../../utils/request') return mocks.requestModule;
      if (request === '../../utils/share') return require('../utils/share');
      throw new Error(`Unexpected require: ${request}`);
    },
  };
  vm.runInNewContext(source, sandbox, { filename });
  assert.ok(definition, `Page was not registered: ${relativePath}`);
  definition.data = JSON.parse(JSON.stringify(definition.data));
  definition.setData = function setData(update, callback) {
    Object.assign(this.data, update);
    if (callback) callback();
  };
  return definition;
}

function testWrongBookUsesGlobalReviewRoutes() {
  const navigations = [];
  const page = loadPage('pages/wrong-book/wrong-book.js', {
    requestModule: { request: async () => [], getUserId: async () => 1 },
    wx: {
      navigateTo: options => navigations.push(options.url),
      showToast: () => { throw new Error('Cross-bank review must not require a bank filter'); },
    },
  });
  page.data.wrongList = [{ bank_id: 11 }, { bank_id: 22 }];
  page.data.starList = [{ bank_id: 11 }, { bank_id: 22 }];
  page.data.filterBankId = '';

  page.practiceWrong();
  page.memorizeWrong();
  page.practiceStar();
  page.memorizeStar();

  assert.deepEqual(navigations, [
    '/pages/practice/practice?mode=wrong',
    '/pages/practice/practice?mode=memorize&source=wrong',
    '/pages/practice/practice?mode=starred',
    '/pages/practice/practice?mode=memorize&source=starred',
  ]);
}

function testWrongBookFilterRefreshesActiveList() {
  const page = loadPage('pages/wrong-book/wrong-book.js', {
    requestModule: { request: async () => [], getUserId: async () => 1 },
    wx: {},
  });
  let wrongLoads = 0;
  let starLoads = 0;
  page._loadWrong = () => { wrongLoads += 1; };
  page._loadStars = () => { starLoads += 1; };
  page.data.activeTab = 'star';
  page.setFilter({ currentTarget: { dataset: { id: '22' } } });
  assert.equal(page.data.filterBankId, 22);
  assert.equal(starLoads, 1);
  assert.equal(wrongLoads, 0);
}

async function testWrongBookLoadsEveryPage() {
  const calls = [];
  const page = loadPage('pages/wrong-book/wrong-book.js', {
    requestModule: {
      getUserId: async () => 1,
      request: async options => {
        calls.push(options.url);
        if (options.url.startsWith('/api/questions/count?')) return { total: 60 };
        const skip = Number((options.url.match(/skip=(\d+)/) || [])[1] || 0);
        const size = skip === 0 ? 50 : 10;
        return Array.from({ length: size }, (_, index) => ({
          record_id: skip + index + 1,
          answered_at: '2026-09-17T10:00:00',
          question: { id: skip + index + 1 },
        }));
      },
    },
    wx: {},
  });

  await page._loadWrong('', false);
  assert.equal(page.data.wrongList.length, 50);
  assert.equal(page.data.wrongTotal, 60);
  assert.equal(page.data.wrongHasMore, true);
  await page._loadWrong('', true);
  assert.equal(page.data.wrongList.length, 60);
  assert.equal(page.data.wrongHasMore, false);
  assert.ok(calls.some(url => url.includes('skip=50')));
}

async function testWrongBookShowsAnswerOptionText() {
  const question = {
    id: 1,
    type: 'single',
    answer: 'B',
    options: [
      { key: 'A', text: '康拉德面' },
      { key: 'B', text: '莫霍面' },
    ],
  };
  const page = loadPage('pages/wrong-book/wrong-book.js', {
    requestModule: {
      getUserId: async () => 1,
      request: async options => {
        if (options.url.startsWith('/api/wrong-questions')) {
          return [{ record_id: 1, user_answer: 'A', answered_at: '', question }];
        }
        if (options.url.startsWith('/api/starred-questions')) return [question];
        if (options.url.startsWith('/api/questions/count')) return { total: 1 };
        throw new Error(`Unexpected request: ${options.url}`);
      },
    },
    wx: {},
  });

  await page._loadWrong('', false);
  assert.equal(page.data.wrongList[0].userAnswerText, 'A. 康拉德面');
  assert.equal(page.data.wrongList[0].correctAnswerText, 'B. 莫霍面');
  await page._loadStars('', false);
  assert.equal(page.data.starList[0].correctAnswerText, 'B. 莫霍面');
}

function testProfileStatsNavigateToExpectedPages() {
  const tabNavigations = [];
  const pageNavigations = [];
  const reviewTabs = [];
  const page = loadPage('pages/profile/profile.js', {
    app: { globalData: {}, isLoggedIn: () => true, promptLogin: async () => true },
    requestModule: { request: async () => ({}), getUserId: async () => 1 },
    wx: {
      switchTab: options => tabNavigations.push(options.url),
      navigateTo: options => pageNavigations.push(options.url),
      setStorageSync: (key, value) => {
        if (key === 'wrongBookActiveTab') reviewTabs.push(value);
      },
    },
  });

  page.goBanks();
  page.goWrongBook();
  page.goStarred();
  page.goReport();
  assert.deepEqual(tabNavigations, [
    '/pages/index/index',
    '/pages/wrong-book/wrong-book',
    '/pages/wrong-book/wrong-book',
  ]);
  assert.deepEqual(reviewTabs, ['wrong', 'star']);
  assert.deepEqual(pageNavigations, ['/pages/report/report']);
}

function testWrongBookConsumesPendingTab() {
  const removed = [];
  const page = loadPage('pages/wrong-book/wrong-book.js', {
    requestModule: { request: async () => [], getUserId: async () => 1 },
    wx: {
      getStorageSync: key => key === 'wrongBookActiveTab' ? 'star' : '',
      removeStorageSync: key => removed.push(key),
    },
  });
  page._loadAll = () => Promise.resolve();
  page.onShow();
  assert.equal(page.data.activeTab, 'star');
  assert.ok(removed.includes('wrongBookActiveTab'));
}

async function testPracticeUsesQuestionBankId() {
  const calls = [];
  const question = {
    id: 101,
    bank_id: 22,
    type: 'single',
    content: 'question',
    options: [{ key: 'A', text: 'answer' }],
    tags: [],
    difficulty: 1,
  };
  const request = async options => {
    calls.push(options);
    if (options.url.startsWith('/api/questions?')) return [question];
    if (options.url.startsWith('/api/questions/count?')) return { total: 1 };
    if (options.url === '/api/answer') {
      return { is_correct: true, correct_answer: 'A', explanation: '', correct_rate: 1 };
    }
    if (options.url === '/api/star') return { is_starred: true };
    if (options.url === '/api/starred-questions') return [];
    throw new Error(`Unexpected request: ${options.url}`);
  };
  const page = loadPage('pages/practice/practice.js', {
    app: {},
    requestModule: { request, getUserId: async () => 1 },
    wx: { showToast: () => {} },
  });
  page.data.bankId = null;
  page.data.mode = 'wrong';

  await page._loadQuestions(0);
  const questionRequest = calls.find(call => call.url.startsWith('/api/questions?'));
  const countRequest = calls.find(call => call.url.startsWith('/api/questions/count?'));
  assert.ok(questionRequest);
  assert.ok(countRequest);
  assert.equal(questionRequest.url.includes('bank_id='), false);
  assert.equal(countRequest.url.includes('bank_id='), false);

  page.setData({ selectedAnswer: 'A' });
  await page.confirmAnswer();
  await page.toggleStar();
  const answerRequest = calls.find(call => call.url === '/api/answer');
  const starRequest = calls.find(call => call.url === '/api/star');
  assert.equal(answerRequest.data.bank_id, 22);
  assert.equal(starRequest.data.bank_id, 22);
}

async function testPracticePaginationKeepsResumeOffset() {
  const calls = [];
  const page = loadPage('pages/practice/practice.js', {
    app: {},
    requestModule: {
      getUserId: async () => 1,
      request: async options => {
        calls.push(options.url);
        if (options.url.includes('/api/questions/count?')) return { total: 250 };
        const match = options.url.match(/skip=(\d+)/);
        const skip = match ? Number(match[1]) : 0;
        const size = skip === 200 ? 50 : 100;
        return Array.from({ length: size }, (_, index) => ({
          id: skip + index + 1,
          bank_id: 7,
          type: 'single',
          options: [{ key: 'A', text: 'answer' }],
        }));
      },
    },
    wx: { showToast: () => {} },
  });
  page.data.bankId = 7;
  page.data.mode = 'sequential';

  await page._loadQuestions(100);
  assert.equal(page.data.startSkip, 100);
  assert.equal(page.data.questions.length, 100);
  assert.equal(page.data.hasMore, true);

  page._showQuestion(99);
  assert.equal(page.data.isLast, false);
  await page.nextQuestion();
  assert.ok(calls.some(url => url.includes('skip=200')));
  assert.equal(page.data.questions.length, 150);
  assert.equal(page.data.hasMore, false);
  page._showQuestion(149);
  assert.equal(page.data.isLast, true);
}

async function testWrongPracticeUsesStableCursorForLaterPages() {
  const calls = [];
  const page = loadPage('pages/practice/practice.js', {
    app: {},
    requestModule: {
      getUserId: async () => 1,
      request: async options => {
        calls.push(options.url);
        if (options.url.includes('/api/questions/count?')) return { total: 101 };
        const after = Number((options.url.match(/after_id=(\d+)/) || [])[1] || 0);
        const start = after ? after + 1 : 1;
        const size = after ? 1 : 100;
        return Array.from({ length: size }, (_, index) => ({
          id: start + index,
          bank_id: 7,
          type: 'single',
          options: [{ key: 'A', text: 'answer' }],
        }));
      },
    },
    wx: { showToast: () => {} },
  });
  page.data.bankId = 7;
  page.data.mode = 'wrong';

  await page._loadQuestions(0);
  assert.equal(page.data.questions.length, 100);
  assert.equal(page._reviewCursorId, 100);
  await page._loadQuestions(100, true);
  assert.ok(calls.some(url => url.includes('after_id=100')));
  assert.equal(calls.some(url => url.includes('mode=wrong&skip=100')), false);
  assert.equal(page.data.questions.length, 101);
  assert.equal(page.data.questions[100].id, 101);
}

async function testMemorizeModeLoadsPastOneHundredQuestions() {
  const calls = [];
  const page = loadPage('pages/practice/practice.js', {
    app: {},
    requestModule: {
      getUserId: async () => 1,
      request: async options => {
        calls.push(options.url);
        if (options.url.includes('/api/questions/count?')) return { total: 120 };
        const after = Number((options.url.match(/after_id=(\d+)/) || [])[1] || 0);
        const start = after ? after + 1 : 1;
        const size = after ? 20 : 100;
        return Array.from({ length: size }, (_, index) => ({
          id: start + index,
          bank_id: 7,
          type: 'single',
          options: [{ key: 'A', text: 'answer' }],
          answer: 'A',
          explanation: '',
        }));
      },
    },
    wx: { showToast: () => {} },
  });
  page.data.mode = 'memorize';
  page.data.isMemorize = true;
  page.data.source = 'starred';

  await page._loadQuestions(0);
  assert.equal(page.data.questions.length, 100);
  assert.equal(page.data.hasMore, true);
  page._showQuestion(99);
  await page.nextQuestion();
  assert.equal(page.data.questions.length, 120);
  assert.equal(page.data.hasMore, false);
  assert.ok(calls.some(url => url.includes('after_id=100')));
  assert.equal(calls.some(url => url.includes('source=starred&skip=100')), false);
}

async function testGuestsBrowseWithoutForcedLogin() {
  const navigations = [];
  const prompts = [];
  // 游客会话语义：有会话（isLoggedIn=true）但 isGuestUser()=true
  const appMock = {
    globalData: {},
    isLoggedIn: () => true,
    isGuestUser: () => true,
    promptLogin: options => {
      prompts.push((options && options.content) || '');
      return Promise.resolve(true);
    },
  };

  // 「我的」页：游客可看统计；上传/管理入口只做主动登录引导，不自动跳转
  const profilePage = loadPage('pages/profile/profile.js', {
    app: appMock,
    requestModule: {
      request: async () => ({ total_answered: 0 }),
      getUserId: async () => 50,
    },
    wx: { navigateTo: options => navigations.push(options.url) },
  });

  profilePage.goUpload();
  profilePage.goManage();
  assert.equal(prompts.length, 2, '游客点击上传/管理应转为主动登录引导');
  profilePage.goReport();
  assert.deepEqual(
    navigations,
    ['/pages/report/report'],
    '游客可查看学习报告（体验功能）',
  );

  profilePage.goEditProfile();
  assert.equal(
    navigations[navigations.length - 1],
    '/pages/login/login',
    '头像卡片在游客态应进入登录页',
  );

  // 首页：无会话（离线）时不请求接口、不跳转
  let indexRequests = 0;
  const indexPage = loadPage('pages/index/index.js', {
    app: appMock,
    requestModule: {
      request: async () => { indexRequests += 1; return []; },
      getUserId: async () => null,
    },
    wx: { navigateTo: options => navigations.push(options.url) },
  });

  await indexPage._refreshForSession();
  assert.equal(indexPage.data.loggedIn, false);
  assert.equal(indexRequests, 0, '离线时首页不得请求接口');
  assert.equal(indexPage.data.banks.length, 0);
  assert.equal(indexPage.data.dailyQuestion, null);

  indexPage.goLogin();
  assert.equal(navigations[navigations.length - 1], '/pages/login/login');

  // 首页：游客会话正常拉取题库（示例题库可浏览）
  const guestIndexPage = loadPage('pages/index/index.js', {
    app: appMock,
    requestModule: {
      request: async () => [],
      getUserId: async () => 50,
    },
    wx: { navigateTo: options => navigations.push(options.url) },
  });
  await guestIndexPage._refreshForSession();
  assert.equal(guestIndexPage.data.loggedIn, true);
  assert.equal(guestIndexPage.data.isGuest, true, '游客会话应展示游客横幅');

  // 游客点「导入新资料」→ 主动登录引导，不得直接跳转
  guestIndexPage.goUpload();
  assert.equal(prompts.length, 3, '游客上传入口应转为主动登录引导');
}

async function testSessionInvalidationSyncsPagesToGuest() {
  const listeners = [];
  const appMock = {
    globalData: {},
    isLoggedIn: () => true,
    onSessionInvalid: listener => {
      listeners.push(listener);
      return () => {};
    },
  };
  const wxMock = { getWindowInfo: () => ({ statusBarHeight: 20 }) };

  const profilePage = loadPage('pages/profile/profile.js', {
    app: appMock,
    requestModule: { request: async () => ({}), getUserId: async () => 1 },
    wx: wxMock,
  });
  profilePage.onLoad();
  profilePage.setData({ loggedIn: true, stats: { total_answered: 42 } });

  const indexPage = loadPage('pages/index/index.js', {
    app: appMock,
    requestModule: { request: async () => [], getUserId: async () => 1 },
    wx: wxMock,
  });
  indexPage.onLoad();
  indexPage.setData({ loggedIn: true, userId: 1, banks: [{ id: 1 }], stats: { total_answered: 1 } });

  assert.equal(listeners.length, 2, '首页与「我的」都应订阅会话失效事件');

  listeners.forEach(listener => listener());

  assert.equal(profilePage.data.loggedIn, false, '会话失效后「我的」页必须回落到游客态');
  assert.equal(Object.keys(profilePage.data.stats).length, 0, '会话失效后不得继续展示旧统计');
  assert.equal(indexPage.data.loggedIn, false, '会话失效后首页必须回落到游客态');
  assert.equal(indexPage.data.banks.length, 0, '会话失效后不得继续展示旧题库');
  assert.equal(indexPage.data.userId, null);
}

async function testPracticeLoadFailureNeverBlanksOrFakesDone() {
  const appMock = { globalData: {}, onSessionInvalid: () => () => {} };

  // 首次加载失败：必须落到错误态，而不是白屏或「练习完成」
  const page = loadPage('pages/practice/practice.js', {
    app: appMock,
    requestModule: {
      getUserId: async () => 1,
      request: async () => { throw new Error('网络错误，请检查连接'); },
    },
    wx: { showToast: () => {} },
  });
  await page._loadQuestions(0);
  assert.equal(page.data.loading, false);
  assert.equal(page.data.done, false, '加载失败不得显示「练习完成」');
  assert.ok(page.data.loadError, '加载失败必须给出错误态，避免白屏');

  // 分页失败：保留已加载题目与进度，只标记 loadMoreError
  const page2 = loadPage('pages/practice/practice.js', {
    app: appMock,
    requestModule: {
      getUserId: async () => 1,
      request: async options => {
        if (options.url.includes('/api/questions/count')) return { total: 120 };
        if (options.url.includes('skip=100')) throw new Error('网络错误');
        return Array.from({ length: 100 }, (_, index) => ({
          id: index + 1,
          bank_id: 7,
          type: 'single',
          options: [{ key: 'A', text: 'answer' }],
          answer: 'A',
          explanation: '',
        }));
      },
    },
    wx: { showToast: () => {} },
  });
  await page2._loadQuestions(0);
  assert.equal(page2.data.questions.length, 100);
  page2._showQuestion(99);
  await page2.nextQuestion();
  assert.equal(page2.data.done, false, '分页失败不得误判为「练习完成」');
  assert.equal(page2.data.loadMoreError, true);
  assert.equal(page2.data.questions.length, 100, '分页失败后已加载题目不得丢失');
}

async function main() {
  testWrongBookUsesGlobalReviewRoutes();
  testWrongBookFilterRefreshesActiveList();
  await testWrongBookLoadsEveryPage();
  await testWrongBookShowsAnswerOptionText();
  testProfileStatsNavigateToExpectedPages();
  await testGuestsBrowseWithoutForcedLogin();
  testWrongBookConsumesPendingTab();
  await testPracticeUsesQuestionBankId();
  await testPracticePaginationKeepsResumeOffset();
  await testWrongPracticeUsesStableCursorForLaterPages();
  await testMemorizeModeLoadsPastOneHundredQuestions();
  await testSessionInvalidationSyncsPagesToGuest();
  await testPracticeLoadFailureNeverBlanksOrFakesDone();
  console.log('miniapp review flow tests passed');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
