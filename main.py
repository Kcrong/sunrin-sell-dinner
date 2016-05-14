import os
import re
import wget

from bs4 import BeautifulSoup
from datetime import date
from flask import Flask, request, jsonify
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound

app = Flask(__name__)

app.config['DEBUG'] = True

try:
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ["DATABASE_URL"]
except KeyError:
    print('Using Memory')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'


db = SQLAlchemy(app)


def get_html(url):
    """
        def example(path, mode):
        with open(path, mode) as f:
            return [line for line in f if condition]

    is pretty much equivalent to:

        def example(path, mode):
        f = open(path, mode)

        try:
            return [line for line in f if condition]
        finally:
            f.close()
    """

    filename = wget.download(url)
    with open(filename, 'r') as f:
        html_data = f.read()

    os.remove(filename)

    return html_data


class Suppress:
    def __init__(self, *exceptions):
        self._exc = exceptions

    def __exit__(self, exctype, excinst, exctb):
        return exctype is not None and issubclass(exctype, self._exc)

    def __enter__(self):
        pass


class Menu(db.Model):
    id = db.Column(db.INTEGER, primary_key=True)
    date = db.Column(db.DATE, nullable=False)
    menu = db.Column(db.String(200), nullable=False)

    def __init__(self, menu, date):
        self.date = date
        if menu == '':
            self.menu = "오늘은 급식이 없습니다."
        else:
            self.menu = menu

    def __repr__(self):
        return "<Menu %s>" % self.date

    @staticmethod
    def month_format(month):
        return ("0" + str(month))[-2:]

    @classmethod
    def parse_menu(cls, year, month):
        url = "http://stu.sen.go.kr/sts_sci_md00_001.do?schulCode=B100000658&insttNm=%EC%84%A0%EB%A6%B0%EC%9D%B8%ED%8" \
              "4%B0%EB%84%B7%EA%B3%A0%EB%93%B1%ED%95%99%EA%B5%90&schulCrseScCode=4&ay=" \
              + str(year) + "&mm=" + Menu.month_format(month)

        soup = BeautifulSoup(get_html(url), "html.parser")

        day_list = soup.find('tbody').findChildren('td')

        for day in day_list:
            content = day.findChild().contents
            try:
                day_data = date.today().replace(day=int(content[0]))
            except ValueError:
                continue
            menu = "".join(['\n' if str(data) == '<br/>' else str(data) for data in content[2:]])

            db.session.add(cls(menu, day_data))

        db.session.commit()

        return cls.today_menu()

    @classmethod
    def today_menu(cls):
        today = date.today()
        menu = cls.query.filter_by(date=today).first()
        if menu:
            return make_message(menu.menu)
        else:
            today = date.today()
            return cls.parse_menu(today.year, today.month)


class Dinner(db.Model):
    id = db.Column(db.INTEGER, primary_key=True)
    price = db.Column(db.INTEGER, nullable=False)
    date = db.Column(db.DATE, nullable=False, default=date.today())
    user_id = db.Column(db.INTEGER, db.ForeignKey('user.id'))
    is_sold = db.Column(db.Boolean, default=False, nullable=False)

    def __init__(self, price, user):
        self.price = price
        self.user = user

    @property
    def info(self):
        return "%s %d 원" % (self.user.name, self.price)

    @property
    def menu(self):
        return Menu.query.filter_by(date=self.date).first()

    @classmethod
    def all_dinner_info(cls):
        all_dinner = [dinner.info for dinner in cls.query.filter_by(is_sold=False).order_by(cls.price).all()]
        if not all_dinner:
            return make_message("판매자가 없습니다")
        else:
            return make_message("구매하고 싶으신 석식을 눌러주세요", buttonlist=all_dinner)


class User(db.Model):
    id = db.Column(db.INTEGER, primary_key=True)
    name = db.Column(db.String(200))
    userkey = db.Column(db.String(200), nullable=False, unique=True)
    phone = db.Column(db.String(200), unique=True)
    all_dinner = db.relationship(Dinner, backref='user')

    def __init__(self, key, number=None):
        self.userkey = key
        self.number = number

    def __repr__(self):
        return "<User %s>" % self.key

    @property
    def dinner(self):
        return db.object_session(self).query(Dinner).filter_by(date=date.today(), is_sold=False) \
            .with_parent(self).first()

    @classmethod
    def get_or_create(cls, key):
        u = cls.query.filter_by(userkey=key).first()

        if not u:
            u = cls(key)
            db.session.add(u)
            db.session.commit()

        return u

    def sold_dinner(self):
        try:
            self.dinner.is_sold = True
        except AttributeError:
            return make_message('판매할 석식을 등록하지 않았습니다!')
        else:
            db.session.commit()

        return make_message('이용해 주셔서 감사합니다.')


def current_request():
    return request.get_json()


def current_user():
    return User.get_or_create(current_request()['user_key'])


def make_message(message, res_type='buttons', buttonlist=None):
    message = {
        'message': {
            'text': message
        },
        'keyboard': {
            'type': res_type
        }
    }

    if buttonlist is not None:
        button_list = ['취소'] + buttonlist
    elif current_user().dinner:
        button_list = ['판매완료', '급식메뉴']
    else:
        button_list = ['급식메뉴', '석식구매', '석식판매', '판매완료']

    if res_type is 'buttons':
        message['keyboard']['buttons'] = button_list

    return message


def want_info(info):
    return {
        '이름': make_message("이름을 입력해 주세요", 'text'),
        '전화번호': make_message("전화번호를 입력해 주세요", 'text'),
        '가격': make_message("판매할 가격을 입력해 주세요", 'text')
    }[info]


def sell_dinner():
    u = current_user()

    if u.dinner:
        return make_message("이미 판매 매물을 등록하셨습니다. '판매완료' 버튼을 눌러주세요!")
    elif u.name is None:
        return want_info('이름')
    elif u.phone is None:
        return want_info('전화번호')
    else:
        return want_info('가격')


def check_buy_message(content):
    data = content.split()
    with Suppress(NotFound):
        if data[-1] == '원' and len(data) == 3:
            return Dinner.query.filter(User.name == data[0] and Dinner.price == data[1]).first_or_404()
    return False


@app.route('/message', methods=['POST'])
def auto_message():
    content = current_request()['content']
    u = current_user()

    try:
        message = {
            '급식메뉴': Menu.today_menu,
            '석식구매': Dinner.all_dinner_info,
            '석식판매': sell_dinner,
            '판매완료': u.sold_dinner,
            '취소': lambda: make_message('취소하셨습니다.')
        }[content]()

    except KeyError:
        checked = check_buy_message(content)

        if checked:
            message = make_message("판매자 전화번호입니다.\n%s" % checked.user.phone)
        elif u.name is None:
            u.name = content
            message = want_info('전화번호')
        elif u.phone is None:
            u.phone = content
            message = want_info('가격')
        else:
            price = re.sub("[^0-9]", "", content)
            db.session.add(Dinner(price, u))
            db.session.commit()
            return jsonify(make_message('성공적으로 등록되었습니다.\n판매시 "판매완료" 버튼을 눌러주세요'))

        db.session.commit()

    return jsonify(message)


@app.route('/friend', methods=['POST'])
def friend():
    db.session.add(User(request.form['user_key']))
    with Suppress(IntegrityError):
        db.session.commit()

    return "SUCCESS"


@app.route('/keyboard')
def keyboard():
    return jsonify({
        'type': 'buttons',
        'buttons': ['급식메뉴', '석식구매', '석식판매', '판매완료']
    })
