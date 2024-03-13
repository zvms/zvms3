from typing import (
    TypeAlias,
    Iterable,
    Literal
)
from operator import itemgetter
from datetime import date

from flask import abort, session

from ..framework import ZvmsError
from ..util import (
    username2userid,
    get_primary_key,
    send_notice_to,
    execute_sql
)
from ..misc import (
    ThoughtStatus,
    Permission,
    ErrorCode,
    VolStatus,
    VolKind,
    VolType
)

SelectResult: TypeAlias = tuple[
    int,  # 总数
    list[tuple[
        int,  # ID
        str,  # 名字
        int,  # 状态
        int,  # 创建者
        str,  # 创建者用户名
        int  # 类型
    ]]]
Classes: TypeAlias = list[tuple[int, int]]


def _select_volunteers(
    where_clause: str,
    args: dict,
    page: int
) -> SelectResult:
    count = execute_sql(
        'SELECT COUNT(*) '
        'FROM volunteer AS vol '
        f'JOIN user ON user.userid = vol.holder {where_clause}',
        **args
    ).fetchone()[0]
    match execute_sql(
        'SELECT vol.id, vol.name, vol.status, vol.holder, user.username, vol.type '
        'FROM volunteer AS vol '
        'JOIN user ON user.userid = vol.holder '
        f'{where_clause} '
        'ORDER BY vol.id DESC '
        'LIMIT 10 '
        'OFFSET :offset',
        **args,
        offset=page * 10
    ).fetchall():
        case None:
            abort(404)
        case data: ...
    return count, data


def _can_signup(volid: int) -> bool:
    return execute_sql(
        'SELECT vol.time >= DATE("NOW") '
        'AND vol.status = 2 '
        'AND NOT EXISTS (SELECT * FROM user_vol AS uv WHERE uv.userid = :userid AND uv.volid = :volid) '
        'AND cv.max > COUNT(uv.userid) '
        'FROM class_vol AS cv '
        'LEFT JOIN user_vol AS uv ON uv.volid = cv.volid '
        'AND uv.userid IN (SELECT user.userid FROM user WHERE user.classid = cv.classid) '
        'JOIN volunteer AS vol ON vol.id = cv.volid '
        'WHERE vol.id = :volid',
        userid=session.get('userid'),
        volid=volid,
        classid=session.get('classid')
    ).fetchone()[0]


def search_volunteers(name: str, page: int) -> SelectResult:
    return _select_volunteers(
        'WHERE name LIKE :name',
        {
            'name': f'%{name}%'
        },
        page
    )


def list_volunteers(page: int) -> SelectResult:
    return _select_volunteers('', {}, page)


def my_volunteers(page: int) -> SelectResult:
    return _select_volunteers(
        'WHERE vol.holder = :userid '
        'OR vol.id IN '
        '(SELECT volid '
        'FROM user_vol '
        'WHERE userid = :userid) '
        'OR vol.id IN '
        '(SELECT volid '
        'FROM class_vol '
        'WHERE classid = :classid) '
        '{}'.format(
            'OR user.classid = :classid ' if Permission.CLASS.authorized()
            else ''
        ),
        {
            'userid': session.get('userid'),
            'classid': session.get('classid')
        },
        page
    )


def volunteer_info(volid: int) -> tuple[
    str,  # 名字
    str,  # 描述
    int,  # 状态
    int,  # 创建者ID
    str,  # 创建者用户名
    int,  # 类型
    int,  # 义工时间
    str,  # 报名时间
    bool,  # 可否报名
    bool,  # 可否审核
    list[tuple[int, str, bool]],  # 参加者
    list[tuple[int, str]]  # 报名者
]:
    match execute_sql(
        'SELECT vol.name, vol.description, vol.status, vol.holder, user.username, vol.type, vol.reward, vol.time, user.classid '
        'FROM volunteer AS vol '
        'JOIN user ON user.userid = vol.holder '
        'WHERE vol.id = :volid',
        volid=volid
    ).fetchone():
        case None:
            abort(404)
        case [*vol_info, holder_classid]: ...
    participants = execute_sql(
        'SELECT uv.userid, user.username, uv.userid = :userid OR :can_view_thoughts OR (:can_view_class_thoughts AND user.classid = :classid)'
        'FROM user_vol AS uv '
        'JOIN user ON user.userid = uv.userid '
        'WHERE uv.volid = :volid AND uv.status != 1 ',
        volid=volid,
        userid=session.get('userid'),
        can_view_thoughts=(Permission.MANAGER |
                           Permission.AUDITOR).authorized(),
        can_view_class_thoughts=Permission.CLASS.authorized(),
        classid=session.get('classid')
    ).fetchall()
    signups = []
    if Permission.CLASS.authorized() and vol_info[2] == VolStatus.ACCEPTED:
        signups = execute_sql(
            'SELECT uv.userid, user.username '
            'FROM user_vol AS uv '
            'JOIN user ON user.userid = uv.userid '
            'WHERE uv.volid = :volid AND uv.status = 1 AND user.classid = :classid ',
            volid=volid,
            classid=int(session.get('classid'))
        ).fetchall()
    can_audit = vol_info[2] == VolStatus.UNAUDITED and Permission.CLASS.authorized() and holder_classid == int(session.get('classid'))
    return *vol_info, can_audit,_can_signup(volid), participants, signups


def _volunteer_helper_pre(classes: Classes) -> None:
    for classid, max in classes:
        if execute_sql(
            'SELECT COUNT(userid) '
            'FROM user '
            'WHERE classid = :classid',
            classid=classid
        ).fetchone()[0] < max:
            raise ZvmsError(ErrorCode, {'classid': classid})


def _volunteer_helper_post(volid: int, classes: Classes) -> None:
    for classid, max in classes:
        execute_sql(
            'INSERT INTO class_vol(classid, volid, max) '
            'VALUES(:classid, :volid, :max)',
            classid=classid,
            volid=volid,
            max=max
        )


def create_volunteer(
    name: str,
    description: str,
    time: date,
    reward: int,
    classes: Classes
) -> int:
    _volunteer_helper_pre(classes)
    execute_sql(
        'INSERT INTO volunteer(name, description, status, holder, type, reward, time) '
        'VALUES(:name, :description, :status, :holder, :type, :reward, :time)',
        name=name,
        description=description,
        type=VolType.INSIDE,
        status=VolStatus.ACCEPTED,
        holder=session.get('userid'),
        reward=reward,
        time=time
    )
    volid = get_primary_key()
    _volunteer_helper_post(volid, classes)
    for cls, max in classes:
        send_notice_to(
            '可报名的义工',
            f'义工[{name}](/volunteer/{volid})已创建, 总共可报名{max}人, 时间{reward}分钟',
            cls,
            True
        )
    return volid


def create_appointed_volunteer(
    name: str,
    description: str,
    type: Literal[VolType.INSIDE, VolType.OUTSIDE],
    reward: int,
    participants: Iterable[str]
) -> int:
    userids = username2userid(participants)
    status = VolStatus.UNAUDITED
    thought_status = ThoughtStatus.WAITING_FOR_SIGNUP_AUDIT
    to_send_notice = False
    if (Permission.CLASS | Permission.MANAGER | Permission.AUDITOR).authorized():
        status = VolStatus.ACCEPTED
        thought_status = ThoughtStatus.DRAFT
    else:
        to_send_notice = True
    execute_sql(
        'INSERT INTO volunteer(name, description, status, holder, time, type, reward) '
        'VALUES(:name, :description, :status, :holder, DATE("NOW"), :type, :reward)',
        name=name,
        description=description,
        status=status,
        holder=session.get('userid'),
        type=type,
        reward=reward
    )
    volid = get_primary_key()
    for userid in userids:
        execute_sql(
            'INSERT INTO user_vol(userid, volid, status, thought, reward) '
            'VALUES(:userid, :volid, :status, "", :reward)',
            userid=userid,
            volid=volid,
            status=thought_status,
            reward=reward
        )
    if to_send_notice:
        match execute_sql(
            'SELECT userid FROM user WHERE classid = :classid AND permission & 1',
            classid=session.get('classid')
        ).fetchone():
            case [secretary]:
                send_notice_to(
                    '义工创建',
                    '你班级的同学[{}](/user/{})创建了义工[{}](/volunteer/{}), 请择日加以审核'.format(
                        session.get('username'),
                        session.get('userid'),
                        name,
                        volid
                    ),
                    secretary
                )
    return volid


def audit_volunteer(
    volid: int,
    status: Literal[VolStatus.ACCEPTED, VolStatus.REJECTED]
) -> None:
    match execute_sql(
        'SELECT name, holder, status FROM volunteer WHERE id = :volid',
        volid=volid
    ).fetchone():
        case None:
            abort(404)
        case [*_, s] if s != VolStatus.UNAUDITED:
            raise ZvmsError(ErrorCode.CANT_AUDIT_VOLUNTEER)
        case [name, holder, _]: ...
    execute_sql(
        'UPDATE volunteer SET status = :status WHERE id = :volid',
        volid=volid,
        status=status
    )
    if status == VolStatus.ACCEPTED:
        execute_sql(
            'UPDATE user_vol SET status = :status WHERE volid = :volid',
            volid=volid,
            status=ThoughtStatus.DRAFT
        )
    send_notice_to(
        '义工过审',
        '你的义工[{}](/volunteer/{})已{}'.format(
            name,
            volid,
            '过审' if status == VolStatus.ACCEPTED else '被拒绝'
        ),
        holder
    )
    participants = execute_sql(
        'SELECT userid FROM user_vol WHERE volid = :volid',
        volid=volid
    ).scalars().all()
    if status == VolStatus.ACCEPTED:
        for participant in participants:
            send_notice_to(
                '义工过审',
                f'你报名的义工[{name}](/volunteer/{volid})已过审, 可以填写感想',
                participant
            )


def create_special_volunteer(
    name: str,
    type: VolType,
    reward: int,
    participants: Iterable[str]
) -> int:
    userids = username2userid(participants)
    execute_sql(
        'INSERT INTO volunteer(name, description, status, holder, time, type, reward) '
        'VALUES(:name, :name, :status, :holder, DATE("NOW"), :type, :reward)',
        name=name,
        status=VolStatus.SPECIAL,
        holder=session.get('userid'),
        type=type,
        reward=reward
    )
    volid = get_primary_key()
    for userid in userids:
        execute_sql(
            'INSERT INTO user_vol(userid, volid, status, thought, reward) '
            'VALUES(:userid, :volid, :status, "", :reward)',
            userid=userid,
            volid=volid,
            status=ThoughtStatus.ACCEPTED,
            reward=reward
        )
        send_notice_to(
            '获得时间',
            f'你由于[{name}](/volunteer/{volid})获得了{type}{reward}时间',
            userid
        )
    return volid


def create_special_volunteer_ex(
    name: str,
    type: VolType,
    participants: list[tuple[str, int]]
) -> None:
    userids = username2userid(map(itemgetter(0), participants))
    execute_sql(
        'INSERT INTO volunteer(name, description, status, holder, time, type, reward) '
        'VALUES(:name, :name, :status, :holder, DATE("NOW"), :type, 0)',
        name=name,
        status=VolStatus.SPECIAL,
        holder=session.get('userid'),
        type=type
    )
    volid = get_primary_key()
    for userid, reward in zip(userids, map(itemgetter(1), participants)):
        execute_sql(
            'INSERT INTO user_vol(userid, volid, status, thought, reward) '
            'VALUES(:userid, :volid, :status, "", :reward)',
            userid=userid,
            volid=volid,
            status=ThoughtStatus.ACCEPTED,
            reward=reward
        )
        send_notice_to(
            '获得时间',
            f'你由于[{name}](/volunteer/{volid})获得了{type}{reward}时间',
            userid
        )
    return volid


def signup_volunteer(volid: int) -> None:
    if not _can_signup(volid):
        raise ZvmsError(ErrorCode.CANT_SIGNUP_FOR_VOLUNTEER)
    status = ThoughtStatus.WAITING_FOR_SIGNUP_AUDIT
    if (Permission.CLASS | Permission.MANAGER).authorized():
        status = ThoughtStatus.DRAFT
    execute_sql(
        'INSERT INTO user_vol(userid, volid, status, thought, reward) '
        'VALUES(:userid, :volid, :status, "", 0)',
        userid=session.get('userid'),
        volid=volid,
        status=status
    )


def _test_signup(userid: int, volid: int) -> None:
    match execute_sql(
        'SELECT COUNT(*) FROM user_vol WHERE userid = :userid AND volid = :volid',
        userid=userid,
        volid=volid
    ).fetchone():
        case [0]:
            raise ZvmsError(ErrorCode.SIGNUP_NOT_EXISTS)


def rollback_volunteer_signup(volid: int, userid: int) -> None:
    if userid != int(session.get('userid')) and not Permission.CLASS.authorized():
        raise ZvmsError(ErrorCode.CANT_ROLLBACK_OTHERS_SIGNUP)
    _test_signup(userid, volid)
    execute_sql(
        'DELETE FROM user_vol WHERE userid = :userid AND volid = :volid',
        userid=userid,
        volid=volid
    )
    execute_sql(
        'DELETE FROM picture WHERE volid = :volid AND userid = :userid',
        userid=userid,
        volid=volid
    )


def accept_volunteer_signup(volid: int, userid: int) -> None:
    _test_signup(userid, volid)
    execute_sql(
        'UPDATE user_vol SET status = :status WHERE userid = :userid AND volid = :volid',
        volid=volid,
        status=VolStatus.ACCEPTED,
        userid=userid
    )
    (volname,) = execute_sql(
        'SELECT name FROM volunteer WHERE id = :volid',
        volid=volid
    ).fetchone()
    send_notice_to(
        '报名过审',
        f'你在[{volname}](/volunteer/{volid})已通过审核, 可以填写感想',
        userid
    )


def delete_volunteer(volid: int) -> None:
    match execute_sql(
        'SELECT holder, name FROM volunteer WHERE id = :volid',
        volid=volid
    ).fetchone():
        case None:
            abort(404)
        case [holder, name]: ...
    if holder != int(session.get('userid')):
        if not Permission.MANAGER.authorized():
            raise ZvmsError(ErrorCode.CANT_DELETE_OTHERS_VOLUNTEER)
        send_notice_to(
            '义工删除', f'你创建的义工[{name}](/volunteer/{volid})被删除', holder)
    execute_sql('DELETE FROM class_vol WHERE volid = :volid', volid=volid)
    execute_sql('DELETE FROM user_vol WHERE volid = :volid', volid=volid)
    execute_sql('DELETE FROM picture WHERE volid = :volid', volid=volid)
    execute_sql('DELETE FROM volunteer WHERE id = :volid', volid=volid)


def detect_volunteer_kind(volid: int, status: int) -> tuple[VolKind, Classes | None]:
    if status == VolStatus.SPECIAL:
        return VolKind.SPECIAL, None
    classes = execute_sql(
        'SELECT classid, max '
        'FROM class_vol '
        'WHERE volid = :volid',
        volid=volid
    ).fetchall()
    if classes:
        return VolKind.INSIDE, classes
    return VolKind.APPOINTED, None


def prepare_modify_volunteer(volid: int) -> tuple[
    VolKind,
    str,  # 名称
    str,  # 描述
    str,  # 举办时间
    int,  # 义工时间
    int,  # 义工类型
    list[tuple[int, int]],  # 参加者
    list[tuple[int, int]]  # 参加班级
]:
    match execute_sql(
        'SELECT holder, name, description, reward, time, status, type '
        'FROM volunteer WHERE id = :volid',
        volid=volid
    ).fetchone():
        case None:
            abort(404)
        case [holder, name, description, reward, time, status, type]:
            if status == VolStatus.REJECTED:
                raise ZvmsError(ErrorCode.CANT_MODIFY_REJECTED_VOLUNTEER)
            if holder != int(session.get('userid')) and not Permission.MANAGER.authorized():
                raise ZvmsError(ErrorCode.CANT_DELETE_OTHERS_VOLUNTEER)
    participants = execute_sql(
        'SELECT userid, reward '
        'FROM user_vol '
        'WHERE volid = :volid',
        volid=volid
    ).fetchall()
    kind, maybe_classes = detect_volunteer_kind(volid, status)
    if kind == VolKind.SPECIAL:
        if len(set(map(itemgetter(1), participants))) == 1:
            participants = [
                (userid, reward if i == 0 else '')
                for i, (userid, reward) in enumerate(participants)
            ]
    return (
        kind,
        name,
        description,
        time,
        reward,
        type,
        participants,
        maybe_classes or []
    )


def _test_vol(volid: int, expected_kind: VolKind) -> None:
    match execute_sql(
        'SELECT status, holder FROM volunteer WHERE id = :volid',
        volid=volid
    ).fetchone():
        case None:
            abort(404)
        case [_, holder] if holder != int(session.get('userid')) and not Permission.MANAGER.authorized():
            raise ZvmsError(ErrorCode.CANT_MODIFY_OTHERS_VOLUNTEER)
        case [status, _]:
            if status == VolStatus.REJECTED:
                raise ZvmsError(ErrorCode.CANT_AUDIT_REJECTED_VOLUNTEER)
            kind, _ = detect_volunteer_kind(volid, status)
            if kind != expected_kind:
                raise ZvmsError(ErrorCode.VOLUNTEER_KIND_MISMATCH)
            return status


def modify_special_volunteer(
    volid: int,
    name: str,
    type: VolType,
    reward: int,
    participants: list[str]
) -> None:
    _test_vol(volid, VolKind.SPECIAL)
    userids = username2userid(participants)
    execute_sql(
        'UPDATE volunteer '
        'SET name = :name, description = :name, type = :type '
        'WHERE id = :volid',
        volid=volid,
        name=name,
        type=type
    )
    execute_sql(
        'DELETE FROM user_vol '
        'WHERE volid = :volid',
        volid=volid
    )
    for userid in userids:
        execute_sql(
            'INSERT INTO user_vol(userid, volid, status, thought, reward) '
            'VALUES(:userid, :volid, :status, "", :reward)',
            userid=userid,
            volid=volid,
            status=ThoughtStatus.ACCEPTED,
            reward=reward
        )


def modify_special_volunteer_ex(
    volid: int,
    name: str,
    type: VolType,
    participants: list[tuple[str, int]]
) -> None:
    _test_vol(volid, VolKind.SPECIAL)
    userids = username2userid(map(itemgetter(0), participants))
    execute_sql(
        'UPDATE volunteer '
        'SET name = :name, description = :name, type = :type '
        'WHERE id = :volid',
        volid=volid,
        name=name,
        type=type
    )
    execute_sql(
        'DELETE FROM user_vol '
        'WHERE volid = :volid',
        volid=volid
    )
    for userid, reward in zip(userids, map(itemgetter(1), participants)):
        execute_sql(
            'INSERT INTO user_vol(userid, volid, status, thought, reward) '
            'VALUES(:userid, :volid, :status, "", :reward)',
            userid=userid,
            volid=volid,
            status=ThoughtStatus.ACCEPTED,
            reward=reward
        )


def modify_volunteer(
    volid: int,
    name: str,
    description: str,
    time: date,
    reward: int,
    classes: Classes
) -> None:
    _test_vol(volid, VolKind.INSIDE)
    _volunteer_helper_pre(classes)
    execute_sql(
        'UPDATE volunteer '
        'SET name = :name, description = :description, reward = :reward, time = :time '
        'WHERE id = :volid',
        volid=volid,
        name=name,
        description=description,
        reward=reward,
        time=time
    )
    execute_sql(
        'DELETE FROM class_vol '
        'WHERE volid = :volid',
        volid=volid
    )
    _volunteer_helper_post(volid, classes)


def modify_appointed_volunteer(
    volid: int,
    name: str,
    description: str,
    type: Literal[VolType.INSIDE, VolType.OUTSIDE],
    reward: int,
    participants: Iterable[str]
) -> None:
    status = _test_vol(volid, VolKind.APPOINTED)
    userids = set(username2userid(participants))
    execute_sql(
        'UPDATE volunteer '
        'SET name = :name, description = :description, type = :type, reward = :reward '
        'WHERE id = :volid',
        volid=volid,
        name=name,
        description=description,
        type=type,
        reward=reward
    )
    former_participants = set(execute_sql(
        'SELECT userid '
        'FROM user_vol '
        'WHERE volid = :volid',
        volid=volid
    ).scalars().all())
    for deprecated in former_participants - userids:
        execute_sql(
            'DELETE FROM user_vol '
            'WHERE volid = :volid AND userid = :userid',
            volid=volid,
            userid=deprecated
        )
    for added in userids - former_participants:
        execute_sql(
            'INSERT INTO user_vol(userid, volid, status, thought, reward) '
            'VALUES(:userid, :volid, :status, "", :reward)',
            userid=added,
            volid=volid,
            status=ThoughtStatus.WAITING_FOR_SIGNUP_AUDIT if status == VolStatus.UNAUDITED else ThoughtStatus.DRAFT,
            reward=reward
        )
    for participant in former_participants:
        execute_sql(
            'UPDATE user_vol SET reward = :reward '
            'WHERE userid = :userid AND volid = :volid',
            reward=reward,
            userid=participant,
            volid=volid
        )
