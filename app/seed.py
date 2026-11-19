from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .models import Plan

def seed_plans(db: Session):
    if db.scalar(select(func.count()).select_from(Plan)): return
    db.add_all([Plan(name="پایه", price_month=99000, traffic_gb=50, devices=2),
                Plan(name="حرفه‌ای", price_month=189000, traffic_gb=0, devices=3),
                Plan(name="ویژه", price_month=299000, traffic_gb=0, devices=5)])
    db.commit()

def seed_content(db: Session):
    from .models import ContentItem
    if db.scalar(select(func.count()).select_from(ContentItem)): return
    db.add_all([ContentItem(kind="faq", title="اشتراکم تمام شد، چه کنم؟", body="از بخش خرید تمدید کنید یا در صورت وجود، دسترسی موقت بگیرید.", sort=1),
                ContentItem(kind="faq", title="چند دستگاه می‌توانم وصل کنم؟", body="تا سقف دستگاه‌های پلن شما.", sort=2),
                ContentItem(kind="faq", title="سرعت پایین است", body="برنامه را به‌روز کنید، سرور دیگری را امتحان کنید یا با پشتیبانی تماس بگیرید.", sort=3),
                ContentItem(kind="rules", title="قوانین استفاده", body="استفاده‌ی غیرقانونی و اشتراک‌گذاری لینک با دیگران ممنوع است. متن این بخش را از پنل ← محتوا ویرایش کنید.", sort=1),
                ContentItem(kind="privacy", title="حریم خصوصی", body="ما فقط اطلاعات لازم برای ارائه‌ی سرویس را نگه می‌داریم. متن این بخش را از پنل ← محتوا ویرایش کنید.", sort=1)])
    db.commit()
