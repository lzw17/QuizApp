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
    app: { globalData: {} },
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

async function main() {
  testWrongBookUsesGlobalReviewRoutes();
  testWrongBookFilterRefreshesActiveList();
  await testWrongBookLoadsEveryPage();
  await testWrongBookShowsAnswerOptionText();
  testProfileStatsNavigateToExpectedPages();
  testWrongBookConsumesPendingTab();
  await testPracticeUsesQuestionBankId();
  await testPracticePaginationKeepsResumeOffset();
  await testWrongPracticeUsesStableCursorForLaterPages();
  await testMemorizeModeLoadsPastOneHundredQuestions();
  console.log('miniapp review flow tests passed');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
