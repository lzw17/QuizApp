"""游客模式的示例题库种子。

游客账号创建时，把这份示例题库复制到游客名下（created_by = 游客 openid），
复用既有的题库可见性规则（bank_access.apply_bank_access），练习/错题本/统计
等路由无需任何改动即可对游客可用。

微信登录迁移时整库随游客数据一起并入正式账号，用户可自行删除。
"""
import logging
from typing import Dict, List

from sqlalchemy.orm import Session

from ..models.question import BankStatus, Question, QuestionBank
from ..models.user import User
from ..utils.time import utc_now

logger = logging.getLogger(__name__)

DEMO_BANK_NAME = "示例题库 · 先试试手感"
GUEST_STALE_DAYS = 30
GUEST_PURGE_LIMIT = 5

DEMO_QUESTIONS: List[Dict] = [
    {
        "type": "single",
        "content": "艾宾浩斯遗忘曲线揭示：遗忘的进程是（　）的。",
        "options": [
            {"key": "A", "text": "先快后慢"},
            {"key": "B", "text": "先慢后快"},
            {"key": "C", "text": "匀速进行"},
            {"key": "D", "text": "随机波动"},
        ],
        "answer": "A",
        "explanation": "艾宾浩斯的实验表明，遗忘在学习之后立即开始，最初遗忘速度很快，之后逐渐减慢，即「先快后慢」。因此复习要赶在大规模遗忘之前进行。",
        "tags": ["学习方法"],
        "difficulty": 2,
    },
    {
        "type": "single",
        "content": "下列哪种做法最符合「间隔重复」（Spaced Repetition）的记忆策略？",
        "options": [
            {"key": "A", "text": "考前一夜把所有内容背完"},
            {"key": "B", "text": "把复习分散在第 1、2、4、7、15 天"},
            {"key": "C", "text": "只阅读一遍教材不做题"},
            {"key": "D", "text": "抄写同一页笔记十遍"},
        ],
        "answer": "B",
        "explanation": "间隔重复的核心是在遗忘临界点安排复习：随着每次成功回忆，复习间隔逐步拉长（如 1→2→4→7→15 天），记忆保持率远高于集中突击。",
        "tags": ["学习方法"],
        "difficulty": 2,
    },
    {
        "type": "single",
        "content": "「费曼学习法」的核心步骤是：学习概念 → 尝试讲给别人听 →（　）→ 简化并类推。",
        "options": [
            {"key": "A", "text": "发现卡壳处后回头重新学习"},
            {"key": "B", "text": "把讲稿背诵得更流利"},
            {"key": "C", "text": "立刻做更难的题"},
            {"key": "D", "text": "换一个概念继续讲"},
        ],
        "answer": "A",
        "explanation": "费曼学习法的关键在于「讲不清楚的地方就是没学懂的地方」：卡壳后回到材料重新学习，再简化重讲，直到能流畅讲清。",
        "tags": ["学习方法"],
        "difficulty": 3,
    },
    {
        "type": "single",
        "content": "做错题本时，下列哪项做法对复盘的价值最低？",
        "options": [
            {"key": "A", "text": "只抄题目和正确答案"},
            {"key": "B", "text": "写下当时的错误思路"},
            {"key": "C", "text": "归纳错误原因的类别"},
            {"key": "D", "text": "定期重做并标记反复出错的题"},
        ],
        "answer": "A",
        "explanation": "错题本的价值在于「暴露思维漏洞」：只抄答案无法定位错误原因。记录错误思路、归纳原因并定期重做，才能真正把错题变成提分点。",
        "tags": ["学习方法"],
        "difficulty": 2,
    },
    {
        "type": "multi",
        "content": "下列关于「主动回忆」（Active Recall）的说法，正确的有（　）。",
        "options": [
            {"key": "A", "text": "合上书本自问自答属于主动回忆"},
            {"key": "B", "text": "反复通读笔记属于主动回忆"},
            {"key": "C", "text": "做题检验属于主动回忆"},
            {"key": "D", "text": "主动回忆比被动重读的记忆保持效果更好"},
        ],
        "answer": "ACD",
        "explanation": "主动回忆要求主动提取记忆（自测、做题），而反复通读是被动输入，提取强度低。认知科学研究一致表明主动回忆的长期保持效果显著优于被动重读。",
        "tags": ["学习方法"],
        "difficulty": 3,
    },
    {
        "type": "multi",
        "content": "备考期保持高效学习，下列做法可取的有（　）。",
        "options": [
            {"key": "A", "text": "把大目标拆解为可量化的小任务"},
            {"key": "B", "text": "连续熬夜刷题，睡眠能省则省"},
            {"key": "C", "text": "利用番茄钟等节奏控制注意力"},
            {"key": "D", "text": "定期自测并根据薄弱点调整计划"},
        ],
        "answer": "ACD",
        "explanation": "睡眠是记忆巩固的关键环节，熬夜刷题得不偿失；目标拆解、节奏控制与基于自测的动态调整都是被广泛验证的高效学习做法。",
        "tags": ["学习方法"],
        "difficulty": 2,
    },
    {
        "type": "judge",
        "content": "「多感官学习风格」（视觉型/听觉型等）已被证实：只按自己偏好的风格学习，效果一定最好。",
        "options": [
            {"key": "A", "text": "正确"},
            {"key": "B", "text": "错误"},
        ],
        "answer": "B",
        "explanation": "「学习风格匹配假说」缺乏可靠实验支持。研究更支持「多通道编码」：内容适合用什么形式呈现就用什么形式，而非固守个人偏好风格。",
        "tags": ["学习方法"],
        "difficulty": 3,
    },
    {
        "type": "judge",
        "content": "根据「测试效应」，做题检验本身就是一种高效的学习方式，而不仅仅是评估手段。",
        "options": [
            {"key": "A", "text": "正确"},
            {"key": "B", "text": "错误"},
        ],
        "answer": "A",
        "explanation": "测试效应（Testing Effect）表明：提取练习（考试、自测）本身就能巩固记忆，其效果常优于等时间的重复学习，所以做题不只是「检验」，更是「学习」。",
        "tags": ["学习方法"],
        "difficulty": 2,
    },
]


def seed_demo_bank(db: Session, openid: str) -> QuestionBank:
    """把示例题库复制到指定 openid 名下，返回创建的题库。"""
    bank = QuestionBank(
        name=DEMO_BANK_NAME,
        description="内置示例题目，登录前即可体验练习、错题本与统计功能",
        cover="",
        category="示例",
        total_count=len(DEMO_QUESTIONS),
        status=BankStatus.ready,
        source_file="",
        source_type="",
        created_by=openid,
    )
    db.add(bank)
    db.flush()
    for order_index, item in enumerate(DEMO_QUESTIONS):
        db.add(
            Question(
                bank_id=bank.id,
                type=item["type"],
                content=item["content"],
                options=item["options"],
                answer=item["answer"],
                explanation=item["explanation"],
                tags=item.get("tags", []),
                difficulty=item.get("difficulty", 3),
                status="active",
                order_index=order_index,
            )
        )
    return bank


def purge_stale_guests(db: Session, *, now=None, limit: int = GUEST_PURGE_LIMIT) -> int:
    """尽力清理超过保留期的游客账号及其全部数据，返回清理数量。

    游客承诺「记录不长期保留」：超过 GUEST_STALE_DAYS 天不活跃的游客账号
    在新游客创建时被顺带清理（每次最多 limit 个，控制单次事务耗时）。
    """
    from datetime import timedelta

    now = now or utc_now()
    cutoff = now - timedelta(days=GUEST_STALE_DAYS)
    stale_guests = (
        db.query(User)
        .filter(User.is_guest.is_(True), User.last_login < cutoff)
        .limit(limit)
        .all()
    )
    purged = 0
    for guest in stale_guests:
        try:
            _delete_guest_data(db, guest)
            purged += 1
        except Exception:
            logger.warning("清理过期游客 %s 失败", guest.openid, exc_info=True)
            db.rollback()
    return purged


def _delete_guest_data(db: Session, guest) -> None:
    from ..models.question import ExamSession, ExamSubmission, GenerateTask, GenerationBatch
    from ..models.user import AnswerRecord, UserProgress

    bank_ids = [
        row[0]
        for row in db.query(QuestionBank.id)
        .filter(QuestionBank.created_by == guest.openid)
        .all()
    ]
    db.query(AnswerRecord).filter(AnswerRecord.user_id == guest.id).delete(
        synchronize_session=False
    )
    db.query(UserProgress).filter(UserProgress.user_id == guest.id).delete(
        synchronize_session=False
    )
    db.query(ExamSubmission).filter(ExamSubmission.user_id == guest.id).delete(
        synchronize_session=False
    )
    db.query(ExamSession).filter(ExamSession.user_id == guest.id).delete(
        synchronize_session=False
    )
    if bank_ids:
        db.query(GenerationBatch).filter(
            GenerationBatch.bank_id.in_(bank_ids)
        ).delete(synchronize_session=False)
        db.query(GenerateTask).filter(
            GenerateTask.bank_id.in_(bank_ids)
        ).delete(synchronize_session=False)
        db.query(Question).filter(Question.bank_id.in_(bank_ids)).delete(
            synchronize_session=False
        )
        db.query(QuestionBank).filter(QuestionBank.id.in_(bank_ids)).delete(
            synchronize_session=False
        )
    db.delete(guest)
    db.commit()
