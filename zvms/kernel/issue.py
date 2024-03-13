from flask import session

from ..framework import ZvmsError
from ..util import execute_sql, inexact_now


def list_issues() -> list[tuple[int, str, str, str]]:
    return execute_sql(
        'SELECT issue.author, user.username, issue.content, issue.time '
        'FROM issue '
        'JOIN user ON issue.author = user.userid '
        'ORDER BY issue.id DESC'
    ).fetchall()


def my_issues() -> tuple[int, list[tuple[str, str]]]:
    issues_posted = execute_sql(
        'SELECT time, content '
        'FROM issue '
        'WHERE author = :author',
        author=session.get('userid')
    ).fetchall()
    issues_thisweek = execute_sql(
        'SELECT COUNT(*) '
        'FROM issue '
        'WHERE author = :author AND time > DATE("NOW", "-7 DAY")',
        author=session.get('userid')
    ).fetchone()[0]
    return issues_thisweek, issues_posted


def post_issue(content: str) -> None:
    times = execute_sql(
        'SELECT COUNT(*) '
        'FROM issue '
        'WHERE author = :id AND time > DATE("NOW", "-7 DAY")',
        id=session.get('userid'),
    ).fetchone()[0]
    if times >= 2:
        raise ZvmsError('反馈已达上限')
    execute_sql(
        'INSERT INTO issue(author, content, time) '
        'VALUES(:author, :content, :time)',
        author=session.get('userid'),
        content=content,
        time=inexact_now()
    )


def clear_issues() -> None:
    execute_sql(
        'DELETE FROM issue'
    )
