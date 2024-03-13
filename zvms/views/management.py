from datetime import date

from flask import (
    Blueprint,
    render_template,
    redirect,
    request
)

from ..util import (
    render_template,
    three_days_later,
)
from ..framework import (
    ZvmsError,
    login_required,
    permission,
    zvms_route,
    url
)
from ..kernel import notice as NoticeKernel
from ..kernel import issue as IssueKernel
from ..misc import Permission

Management = Blueprint('Management', __name__, url_prefix='/management')


@zvms_route(Management, url(''), 'GET')
@login_required
@permission(Permission.MANAGER)
def index():
    return render_template(
        'zvms/management.html',
        issues=IssueKernel.list_issues(),
        three_days_later=three_days_later().isoformat()
    )


@zvms_route(Management, url.send_notice)
@login_required
@permission(Permission.MANAGER)
def send_notice(
    title: str,
    content: str,
    school: bool,
    anonymous: bool,
    targets: list[str],
    expire: date
):
    if school:
        NoticeKernel.send_school_notice(
            title,
            content,
            anonymous,
            expire
        )
    else:
        if not targets:
            raise ZvmsError('应至少提供一个目标')
        NoticeKernel.send_notice(
            title,
            content,
            anonymous,
            targets,
            expire
        )
    return redirect('/management')


@zvms_route(Management, url.edit_notices, 'GET')
@login_required
@permission(Permission.MANAGER)
def edit_notices_get():
    return render_template(
        'zvms/edit_notices.html',
        notices=[
            (*spam, list(enumerate(targets)))
            for *spam, targets in NoticeKernel.list_notices()
        ]
    )


@zvms_route(Management, url.edit_notices)
@login_required
@permission(Permission.MANAGER)
def edit_notices_post(noticeid: int, title: str, content: str, targets: list[str]):
    NoticeKernel.edit_notice(
        noticeid,
        title,
        content,
        targets
    )
    return redirect('/management/edit-notices')


@zvms_route(Management, url.delete_notice, 'POST')
@login_required
@permission(Permission.MANAGER)
def delete_notice(noticeid: int):
    NoticeKernel.delete_notice(noticeid)
    return redirect('/management/edit-notices')


@zvms_route(Management, url.issue.clear)
@login_required
@permission(Permission.ADMIN)
def clear_issues():
    IssueKernel.clear_issues()
    return redirect(request.referrer)