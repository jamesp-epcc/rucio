# Copyright European Organization for Nuclear Research (CERN) since 2012
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import hashlib
from typing import TYPE_CHECKING, Optional

from sqlalchemy import and_, delete, func, select, update

from rucio.common.exception import DatabaseException
from rucio.common.utils import pid_exists
from rucio.db.sqla.models import Heartbeat
from rucio.db.sqla.session import read_session, transactional_session

if TYPE_CHECKING:
    from threading import Thread
    from typing import TypedDict

    from sqlalchemy.orm import Session

    class HeartbeatDict(TypedDict):
        readable: Optional[str]
        hostname: str
        pid: int
        thread_name: Optional[str]
        updated_at: datetime.datetime
        created_at: datetime.datetime
        payload: Optional[str]
        test: int

DEFAULT_EXPIRATION_DELAY = datetime.timedelta(days=1).total_seconds()


@transactional_session
def sanity_check(
    executable: str,
    hostname: str,
    hash_executable: Optional[str] = None,
    pid: Optional[int] = None,
    thread: Optional["Thread"] = None,
    expiration_delay: float = DEFAULT_EXPIRATION_DELAY,
    *,
    session: "Session"
) -> None:
    """
    sanity_check wrapper to ignore DatabaseException errors.

    :param executable: Executable name as a string, e.g., conveyor-submitter.
    :param hostname: Hostname as a string, e.g., rucio-daemon-prod-01.cern.ch.
    :param hash_executable: Hash of the executable.
    :param pid: UNIX Process ID as a number, e.g., 1234.
    :param thread: Python Thread Object.
    :param expiration_delay: time (in seconds) after which any inactive health check will be removed
    :param session: The database session in use.
    """
    try:
        _sanity_check(executable=executable, hostname=hostname, hash_executable=hash_executable,
                      expiration_delay=expiration_delay, session=session)
        if pid:
            live(executable=executable, hostname=hostname,
                 pid=pid, thread=thread, session=session)
    except DatabaseException:
        pass


@transactional_session
def _sanity_check(
    executable: str,
    hostname: str,
    hash_executable: Optional[str] = None,
    expiration_delay: float = DEFAULT_EXPIRATION_DELAY,
    *,
    session: "Session"
) -> None:
    """
    Check if processes on the host are still running.

    :param executable: Executable name as a string, e.g., conveyor-submitter.
    :param hostname: Hostname as a string, e.g., rucio-daemon-prod-01.cern.ch.
    :param hash_executable: Hash of the executable.
    :param expiration_delay: time (in seconds) after which any inactive health check will be removed
    :param session: The database session in use.
    """
    base_stmt = select(
        Heartbeat.pid
    ).distinct(
    ).where(
        Heartbeat.hostname == hostname
    )
    if executable:
        if not hash_executable:
            hash_executable = calc_hash(executable)

        stmt = base_stmt.where(
            Heartbeat.executable == hash_executable
        )
        for pid in session.execute(stmt).scalars().all():
            if not pid_exists(pid):
                stmt = delete(
                    Heartbeat
                ).where(
                    and_(Heartbeat.executable == hash_executable,
                         Heartbeat.hostname == hostname,
                         Heartbeat.pid == pid)
                )
                session.execute(stmt)
    else:
        for pid in session.execute(base_stmt).scalars().all():
            if not pid_exists(pid):
                stmt = delete(
                    Heartbeat
                ).where(
                    and_(Heartbeat.hostname == hostname,
                         Heartbeat.pid == pid)
                )
                session.execute(stmt)

    if expiration_delay:
        cardiac_arrest(older_than=expiration_delay, session=session)


@transactional_session
def live(
    executable: str,
    hostname: str,
    pid: int,
    thread: Optional["Thread"] = None,
    older_than: int = 600,
    hash_executable: Optional[str] = None,
    payload: Optional[str] = None,
    *,
    session: "Session"
) -> dict[str, int]:
    """
    Register a heartbeat for a process/thread on a given node.
    The executable name is used for the calculation of thread assignments.
    Removal of stale heartbeats is done as a scheduled database job.

    TODO: Returns an assignment dictionary for the given executable.

    :param executable: Executable name as a string, e.g., conveyor-submitter.
    :param hostname: Hostname as a string, e.g., rucio-daemon-prod-01.cern.ch.
    :param pid: UNIX Process ID as a number, e.g., 1234.
    :param thread: Python Thread Object.
    :param older_than: Ignore specified heartbeats older than specified nr of seconds.
    :param hash_executable: Hash of the executable.
    :param payload: Payload identifier which can be further used to identify the work a certain thread is executing.
    :param session: The database session in use.

    :returns heartbeats: Dictionary {assign_thread, nr_threads}
    """
    if not hash_executable:
        hash_executable = calc_hash(executable)

    if thread:
        thread_id = thread.ident
        thread_name = thread.name
    else:
        thread_id = 0
        thread_name = "thread"

    # upsert the heartbeat
    stmt = update(
        Heartbeat
    ).where(
        and_(Heartbeat.executable == hash_executable,
             Heartbeat.hostname == hostname,
             Heartbeat.pid == pid,
             Heartbeat.thread_id == thread_id)
    ).values({
        Heartbeat.updated_at: datetime.datetime.utcnow(),
        Heartbeat.payload: payload
    })
    if not session.execute(stmt).rowcount:
        Heartbeat(executable=hash_executable,
                  readable=executable[:Heartbeat.readable.property.columns[0].type.length],
                  hostname=hostname,
                  pid=pid,
                  thread_id=thread_id,
                  thread_name=thread_name,
                  payload=payload).save(session=session)

    # assign thread identifier
    stmt = select(
        Heartbeat.hostname,
        Heartbeat.pid,
        Heartbeat.thread_id
    ).with_hint(
        Heartbeat,
        'INDEX(HEARTBEATS HEARTBEATS_PK)',
        'oracle'
    ).where(
        and_(Heartbeat.executable == hash_executable,
             Heartbeat.updated_at >= datetime.datetime.utcnow() - datetime.timedelta(seconds=older_than))
    ).group_by(
        Heartbeat.hostname,
        Heartbeat.pid,
        Heartbeat.thread_id
    ).order_by(
        Heartbeat.hostname,
        Heartbeat.pid,
        Heartbeat.thread_id
    )
    result = session.execute(stmt).all()

    # there is no universally applicable rownumber in SQLAlchemy
    # so we have to do it in Python
    assign_thread = 0
    for r in range(len(result)):
        if result[r][0] == hostname and result[r][1] == pid and result[r][2] == thread_id:
            assign_thread = r
            break

    return {'assign_thread': assign_thread,
            'nr_threads': len(result)}


@transactional_session
def die(
    executable: str,
    hostname: str,
    pid: int,
    thread: "Thread",
    older_than: Optional[int] = None,
    hash_executable: Optional[str] = None,
    *,
    session: "Session"
) -> None:
    """
    Remove a single heartbeat older than specified.

    :param executable: Executable name as a string, e.g., conveyor-submitter
    :param hostname: Hostname as a string, e.g., rucio-daemon-prod-01.cern.ch
    :param pid: UNIX Process ID as a number, e.g., 1234
    :param thread: Python Thread Object
    :param older_than: Removes specified heartbeats older than specified nr of seconds
    :param hash_executable: Hash of the executable.
    :param session: The database session in use.
    """
    if not hash_executable:
        hash_executable = calc_hash(executable)

    stmt = delete(
        Heartbeat
    ).where(
        and_(Heartbeat.executable == hash_executable,
             Heartbeat.hostname == hostname,
             Heartbeat.pid == pid,
             Heartbeat.thread_id == thread.ident)
    )

    if older_than:
        stmt = stmt.where(
            Heartbeat.updated_at < datetime.datetime.utcnow() - datetime.timedelta(seconds=older_than)
        )
    session.execute(stmt)


@transactional_session
def cardiac_arrest(older_than: Optional[int] = None, *, session: "Session") -> None:
    """
    Removes all heartbeats older than specified.

    :param older_than: Removes all heartbeats older than specified nr of seconds
    :param session: The database session in use.
    """

    stmt = delete(
        Heartbeat
    )

    if older_than:
        stmt = stmt.where(
            Heartbeat.updated_at < datetime.datetime.utcnow() - datetime.timedelta(seconds=older_than)
        )
    session.execute(stmt)


@read_session
def list_heartbeats(*, session: "Session") -> list["HeartbeatDict"]:
    """
    List all heartbeats.

    :param session: The database session in use.

    :returns: List of dicts
    """

    stmt = select(
        Heartbeat.readable,
        Heartbeat.hostname,
        Heartbeat.pid,
        Heartbeat.thread_name,
        Heartbeat.updated_at,
        Heartbeat.created_at,
        Heartbeat.payload
    ).order_by(
        Heartbeat.readable,
        Heartbeat.hostname,
        Heartbeat.thread_name
    )

    result = session.execute(stmt).all()
    json_result = []
    for element in result:
        json_result.append(element._asdict())
    return json_result


@read_session
def list_payload_counts(
    executable: str,
    older_than: int = 600,
    hash_executable: Optional[str] = None,
    *,
    session: "Session"
) -> dict[str, int]:
    """
    Give the counts of number of threads per payload for a certain executable.

    :param executable: Executable name as a string, e.g., conveyor-submitter
    :param older_than: Removes specified heartbeats older than specified nr of seconds
    :param hash_executable: Hash of the executable.
    :param session: The database session in use.

    :returns: Dict
    """

    if not hash_executable:
        hash_executable = calc_hash(executable)
    stmt = select(
        Heartbeat.payload,
        func.count(Heartbeat.payload)
    ).where(
        and_(Heartbeat.executable == hash_executable,
             Heartbeat.updated_at >= datetime.datetime.utcnow() - datetime.timedelta(seconds=older_than))
    ).group_by(
        Heartbeat.payload
    ).order_by(
        Heartbeat.payload
    )

    return dict((payload, count) for payload, count in session.execute(stmt).all() if payload)


def calc_hash(executable: str) -> str:
    """
    Calculates a SHA256 hash.

    return: String of hexadecimal hash
    """
    return hashlib.sha256(executable.encode('utf-8')).hexdigest()
