#!/usr/bin/env python3

# Copyright (C) 2025 Dustin Darcy <ScarcityHypothesis.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from collections import OrderedDict, defaultdict
import fnmatch
import psutil

VERSION_STRING = "0.2.6.0"

"""
- We detect not only UNC paths, but also if the drive is a remote or subst drive that references UNC.
- Then we do the same zone fix or warning approach if user consents.
- Everything else stays the same from 0.2.5 (shell_execute_runas for WinError 740, etc.).
"""

#Versions:
# 0.2.6 - UNC corrections & checking for substs and other virtual paths, zone fixes, and permission issues
# 0.2.5 - Added 'attempt_zone_fix()' to optionally modify the user's zone registry keys if we detect a UNC or network path error. Removed any 'try_local_copy_and_launch'
# 0.2.4 - If WinError 740 (requires elevation) launching a process, we do a "runas" fallback using ShellExecuteEx (helps with Windows services)
# 0.2.3 - Capture baseline processes at 'load'. After launch, check the system's ps list to confirm presence over cmdline/pid. Fallback if fail. If --once-only is active, skip launch if exe is running.
# 0.2.0 - Fallback mechanism for "run" action if outside timeout (--fallback-exe / --no-fallback-exe).
# 0.1.0 - Basic functionality for capturing snapshots, comparing, and performing actions based on differences
# 0.0.7 - Added support for sorting services based on dependencies in Windows
# 0.0.6 - Added support for saving initial and modified snapshots in delta creation
# 0.0.5 - Added support for capturing snapshots with delays and waiting for user input
# 0.0.4 - Added support for reverting changes captured in a delta
# 0.0.3 - Added support for delays between actions and confirmation prompts
# 0.0.2 - Added support for filtering processes and services based on include/exclude patterns
# 0.0.1 - Added support for Windows services and actions to start, stop, or restart services

if os.name == 'nt':
    import win32service
    import win32serviceutil
    import win32api
    import win32con
    import pywintypes
    # We'll also do a shell runas approach:
    from win32com.shell import shell
    import ctypes
    import winreg   # We'll use this to set the zone map if user agrees
else:
    pass  # Placeholder for Unix-like systems

# Default exclude list for critical system processes
DEFAULT_EXCLUDES = [
    'System',
    'System Idle Process',
    'svchost.exe',
    'csrss.exe',
    'wininit.exe',
    'winlogon.exe',
    'services.exe',
    'lsass.exe',
    # Add other critical processes as needed
]

def setup_logging(verbose=False, log_file=None):
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers
    )

def save_snapshot(snapshot_file, snapshot):
    logging.info(f"Saving snapshot to {snapshot_file}")
    with open(snapshot_file, 'w') as f:
        json.dump(snapshot, f, indent=4)
    logging.info("Snapshot saved successfully.")

def load_snapshot(snapshot_file):
    logging.info(f"Loading snapshot from {snapshot_file}")
    with open(snapshot_file, 'r') as f:
        snapshot = json.load(f)
    return snapshot

def get_current_processes():
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline', 'create_time']):
        try:
            info = proc.info
            ordered_info = OrderedDict()
            ordered_info['name'] = info.get('name')
            ordered_info['pid'] = info.get('pid')
            ordered_info['exe'] = info.get('exe')
            ordered_info['cmdline'] = info.get('cmdline')
            ordered_info['create_time'] = info.get('create_time')
            processes.append(ordered_info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes

def get_current_services():
    if os.name == 'nt':
        # Windows-specific service handling
        return get_windows_services()
    else:
        # Placeholder for Unix-like systems
        pass
    return []

def get_windows_services():
    services = []
    try:
        # Open the service control manager
        hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)

        # Enumerate all services
        statuses = win32service.EnumServicesStatus(hscm)

        for svc in statuses:
            service_name = svc[0]       # Service name (unique identifier)
            display_name = svc[1]       # Display name (user-friendly)
            service_status = svc[2]

            # Access the 'CurrentState' from the service_status tuple
            status_code = service_status[1]  # Index 1 corresponds to 'CurrentState'

            status_str = {
                win32service.SERVICE_STOPPED: 'Stopped',
                win32service.SERVICE_START_PENDING: 'Start Pending',
                win32service.SERVICE_STOP_PENDING: 'Stop Pending',
                win32service.SERVICE_RUNNING: 'Running',
                win32service.SERVICE_CONTINUE_PENDING: 'Continue Pending',
                win32service.SERVICE_PAUSE_PENDING: 'Pause Pending',
                win32service.SERVICE_PAUSED: 'Paused',
            }.get(status_code, f'Unknown ({status_code})')

            ordered_service = OrderedDict()
            ordered_service['service_name'] = service_name
            ordered_service['display_name'] = display_name
            ordered_service['status'] = status_str

            services.append(ordered_service)

        # Close the service control manager handle
        win32service.CloseServiceHandle(hscm)
    except Exception as e:
        logging.error(f"Error fetching Windows services: {e}")
    return services

def create_process_uid(proc):
    exe = proc.get('exe') or ''
    cmdline = ' '.join(proc.get('cmdline') or [])
    create_time = int(proc.get('create_time') or 0)  # Convert to integer
    return f"{exe}|{cmdline}|{create_time}"

def filter_item(name, include, exclude):
    if exclude is None:
        exclude = []
    merged_excludes = list(exclude) + DEFAULT_EXCLUDES

    if include:
        if not any(fnmatch.fnmatch(name, pattern) for pattern in include):
            return False

    if merged_excludes:
        if any(fnmatch.fnmatch(name, pattern) for pattern in merged_excludes):
            return False

    return True

def compare_snapshots(snapshot1, snapshot2, include=None, exclude=None):
    delta = {
        'processes_terminated': [],
        'processes_started': [],
        'services': []
    }

    # Process comparison using UID
    s1_procs = {create_process_uid(proc): proc for proc in snapshot1['processes']}
    s2_procs = {create_process_uid(proc): proc for proc in snapshot2['processes']}

    # Processes terminated
    for uid in s1_procs:
        if uid not in s2_procs:
            proc = s1_procs[uid]
            if filter_item(proc['name'], include, exclude):
                delta['processes_terminated'].append(proc)

    # Processes started
    for uid in s2_procs:
        if uid not in s1_procs:
            proc = s2_procs[uid]
            if filter_item(proc['name'], include, exclude):
                delta['processes_started'].append(proc)

    # Service comparison
    s1_svcs = {svc['service_name']: svc for svc in snapshot1['services']}
    s2_svcs = {svc['service_name']: svc for svc in snapshot2['services']}

    for name in s1_svcs:
        svc1 = s1_svcs[name]
        svc2 = s2_svcs.get(name)
        if svc2:
            if svc1['status'] != svc2['status']:
                # Service status has changed
                if filter_item(svc1['service_name'], include, exclude):
                    delta['services'].append({
                        'service_name': svc1['service_name'],
                        'display_name': svc1['display_name'],
                        'status_before': svc1['status'],
                        'status_after': svc2['status']
                    })
        else:
            # Service no longer exists in snapshot2
            if filter_item(svc1['service_name'], include, exclude):
                delta['services'].append({
                    'service_name': svc1['service_name'],
                    'display_name': svc1['display_name'],
                    'status_before': svc1['status'],
                    'status_after': 'Not Present'
                })

    # Optionally detect new services
    for name in s2_svcs:
        if name not in s1_svcs:
            svc2 = s2_svcs[name]
            if filter_item(svc2['service_name'], include, exclude):
                delta['services'].append({
                    'service_name': svc2['service_name'],
                    'display_name': svc2['display_name'],
                    'status_before': 'Not Present',
                    'status_after': svc2['status']
                })

    return delta

def get_service_status(service_name):
    if os.name != 'nt':
        return 'Unknown'
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        service = win32service.OpenService(scm, service_name, win32service.SERVICE_QUERY_STATUS)
        status = win32service.QueryServiceStatus(service)[1]
        win32service.CloseServiceHandle(service)
        win32service.CloseServiceHandle(scm)
        status_str = {
            win32service.SERVICE_STOPPED: 'Stopped',
            win32service.SERVICE_RUNNING: 'Running',
            win32service.SERVICE_START_PENDING: 'Start Pending',
            win32service.SERVICE_STOP_PENDING: 'Stop Pending',
            win32service.SERVICE_CONTINUE_PENDING: 'Continue Pending',
            win32service.SERVICE_PAUSE_PENDING: 'Pause Pending',
            win32service.SERVICE_PAUSED: 'Paused',
        }.get(status, f'Unknown ({status})')
        return status_str
    except Exception as e:
        logging.error(f"Could not query status of service {service_name}: {e}")
        return 'Unknown'

def get_service_dependencies():
    dependencies = {}
    if os.name != 'nt':
        return dependencies
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
        services = win32service.EnumServicesStatus(scm)
        for svc in services:
            service_name = svc[0]
            try:
                service_handle = win32service.OpenService(scm, service_name, win32service.SERVICE_QUERY_CONFIG)
                config = win32service.QueryServiceConfig(service_handle)
                dep_names = config[6]  # Dependencies
                dependencies[service_name] = dep_names
                win32service.CloseServiceHandle(service_handle)
            except Exception as e:
                logging.error(f"Could not get dependencies for service {service_name}: {e}")
        win32service.CloseServiceHandle(scm)
    except Exception as e:
        logging.error(f"Error building service dependencies: {e}")
    return dependencies

def sort_services_by_dependencies(services, service_dependencies):
    # Implement a topological sort
    service_names = [svc['service_name'] for svc in services]
    dependency_graph = defaultdict(list)
    for svc_name in service_names:
        deps = service_dependencies.get(svc_name, [])
        for dep in deps:
            if dep in service_names:
                dependency_graph[svc_name].append(dep)

    visited = set()
    stack = []

    def visit(svc_name):
        if svc_name in visited:
            return
        visited.add(svc_name)
        for dep in dependency_graph.get(svc_name, []):
            visit(dep)
        stack.append(svc_name)

    for svc_name in service_names:
        visit(svc_name)

    # Reverse the stack to get the correct order
    sorted_service_names = stack[::-1]

    # Reorder the services list based on the sorted names
    svc_dict = {svc['service_name']: svc for svc in services}
    sorted_services = [svc_dict[name] for name in sorted_service_names if name in svc_dict]

    return sorted_services

def shell_execute_runas(exe_path, args=None):
    """
	Fallback for WinError 740: run as admin via ShellExecuteEx.
	Attempt ShellExecuteEx with 'runas' to bypass WinError 740.
    If user is truly admin or can elevate, Windows should proceed.
    This might still show a UAC prompt.
    """
    if os.name != 'nt':
        logging.error("ShellExecuteEx runas is only implemented on Windows.")
        return False

    if args is None:
        args = []
    params = ' '.join(args)

    try:
        # Attempt runas
        rc = shell.ShellExecuteEx(
            lpVerb='runas',
            lpFile=exe_path,
            lpParameters=params,
            nShow=win32con.SW_SHOWNORMAL
        )
        # We won't necessarily wait for it to finish, but rc includes hProcess, etc.
        logging.info(f"ShellExecuteEx runas succeeded for {exe_path}")
        return True
    except Exception as e:
        logging.error(f"ShellExecuteEx runas failed for {exe_path}: {e}")
        return False


# Attempt to add the domain/server to the local intranet zone to fix UNC issues.
def attempt_zone_fix(server_name):
    """
    Add the server_name to the local intranet zone in the registry if user agrees.
    """
    if os.name != 'nt':
        logging.warning("Zone fix is only relevant on Windows.")
        return False

    # e.g. HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings\ZoneMap\Domains\[server_name]
    # "*": REG_DWORD = 1 (Local Intranet)
    # or possibly 2 (Trusted Sites), but let's do 1 for intranet.
    root_key = winreg.HKEY_CURRENT_USER
    zone_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings\ZoneMap\Domains"
    try:
        # Create or open the domain key
        with winreg.CreateKeyEx(root_key, zone_path + "\\" + server_name, 0, winreg.KEY_WRITE) as domain_key:
            # Then set "*"
            winreg.SetValueEx(domain_key, "*", 0, winreg.REG_DWORD, 1)
        logging.info(f"Added {server_name} to Local Intranet zone (1). Re-run process to see if it helps.")
        return True
    except Exception as e:
        logging.error(f"Could not add {server_name} to Local Intranet zone: {e}")
        return False

# NEW: Use kernel32.GetDriveTypeW to see if it's remote or local
def drive_is_remote_or_subst(drive_letter):
    """
    Returns True if the drive is remote or a subst, i.e. not DRIVE_FIXED.
    https://docs.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew
    """
    if not drive_letter.endswith('\\'):
        drive_letter += '\\'
    DRIVE_UNKNOWN = 0
    DRIVE_NO_ROOT_DIR = 1
    DRIVE_REMOVABLE = 2
    DRIVE_FIXED = 3
    DRIVE_REMOTE = 4
    DRIVE_CDROM = 5
    DRIVE_RAMDISK = 6

    dt = ctypes.windll.kernel32.GetDriveTypeW(drive_letter)
    logging.debug(f"GetDriveType({drive_letter}) = {dt}")
    # If dt == DRIVE_REMOTE, it's definitely a network / mapped. If dt == 0 or 1, it might not be real.
    return (dt == DRIVE_REMOTE or dt == DRIVE_UNKNOWN or dt == DRIVE_NO_ROOT_DIR)

def perform_actions(delta, actions, delay=0, confirm=False, revert=False,
                    fallback_exe=True, skip_cmdline=False, once_only=False,
                    baseline_procs=None):
    """
    baseline_procs: an initial list of processes (from get_current_processes())
    which we use to track if something is 'already running' if once_only is True.
    """
    for action in actions:
        if action == 'close':
            if revert:
                # "Revert" close => Stop services that were Running before (so you'd be returning them to the prior state)
                services_to_stop = [
                    svc for svc in delta.get('services', [])
                    if svc.get('status_before') == 'Stopped'
                ]
                stop_services(services_to_stop, confirm, delay)
                if delay > 0:
                    logging.info(f"Waiting {delay} ms after stopping services.")
                    time.sleep(delay / 1000.0)
                # Close processes that have started
                close_processes(delta.get('processes_started', []), confirm, delay)
            else:
                # "Forward" close => Stop services that are 'Stopped' in snapshot2
                services_to_stop = [
                    svc for svc in delta.get('services', [])
                    if svc.get('status_after') == 'Stopped'
                ]
                stop_services(services_to_stop, confirm, delay)
                if delay > 0:
                    logging.info(f"Waiting {delay} ms after stopping services.")
                    time.sleep(delay / 1000.0)
                # Close processes that have terminated
                close_processes(delta.get('processes_terminated', []), confirm, delay)

        elif action == 'run':
            if revert:
                # "Revert" run => Start services that were previously Running
                services_to_start = [
                    svc for svc in delta.get('services', [])
                    if svc.get('status_before') == 'Running'
                ]
                start_services(services_to_start, confirm, delay)
                if delay > 0:
                    logging.info(f"Waiting {delay} ms after starting services.")
                    time.sleep(delay / 1000.0)
                # Start processes that were "terminated"
                run_processes(delta.get('processes_terminated', []), confirm, delay,
                              fallback_exe, skip_cmdline, once_only, baseline_procs)
            else:
                # "Forward" run => Start services that are 'Running' in snapshot2
                services_to_start = [
                    svc for svc in delta.get('services', [])
                    if svc.get('status_after') == 'Running'
                ]
                start_services(services_to_start, confirm, delay)
                if delay > 0:
                    logging.info(f"Waiting {delay} ms after starting services.")
                    time.sleep(delay / 1000.0)
                # Start processes that were "started"
                run_processes(delta.get('processes_started', []), confirm, delay,
                              fallback_exe, skip_cmdline, once_only, baseline_procs)

        elif action == 'restart':
            # Restart services first
            services_to_restart = delta.get('services', [])
            restart_services(services_to_restart, confirm, delay)
            if delay > 0:
                logging.info(f"Waiting {delay} ms after restarting services.")
                time.sleep(delay / 1000.0)
            # Restart processes that have changed
            processes_to_restart = (delta.get('processes_started', []) +
                                    delta.get('processes_terminated', []))
            restart_processes(processes_to_restart, confirm, delay,
                              fallback_exe, skip_cmdline, once_only, baseline_procs)
        # Finally, wait between multiple actions if user specified

        if delay > 0:
            logging.info(f"Waiting {delay} ms before next action.")
            time.sleep(delay / 1000.0)

def stop_services(services, confirm, delay=0):
    """Stop each service in the given list, optionally prompting for confirmation."""
    if os.name != 'nt':
        logging.warning("Service management not implemented for this OS.")
        return

    # Build a dependency graph
    service_dependencies = get_service_dependencies()

    # Sort services based on dependencies
    services_to_stop = sort_services_by_dependencies(services, service_dependencies)

    for svc in services_to_stop:
        service_name = svc['service_name']
        display_name = svc['display_name']
        current_status = get_service_status(service_name)
        if current_status == 'Stopped':
            logging.info(f"Service {display_name} ({service_name}) is already stopped.")
            continue
        if confirm:
            resp = input(f"Do you want to stop service {display_name} ({service_name})? [y/N]: ")
            if resp.lower() != 'y':
                continue
        try:
            win32serviceutil.StopService(service_name)
            logging.info(f"Stopped service {display_name} ({service_name}).")
        except Exception as e:
            logging.error(f"Could not stop service {display_name} ({service_name}): {e}")

        if delay > 0:
            logging.info(f"Waiting for {delay} milliseconds after stopping service {display_name}.")
            time.sleep(delay / 1000.0)

def close_processes(processes, confirm, delay=0):
    """Terminate the processes listed, if they're currently running."""
    # Get current processes
    current_processes = list(psutil.process_iter(['pid', 'name', 'exe', 'cmdline']))
    for proc_info in processes:
        exe = proc_info.get('exe') or ''
        cmdline = proc_info.get('cmdline') or []
        matched = False
        for proc in current_processes:
            try:
                if (proc.info.get('exe') == exe and
                        proc.info.get('cmdline') == cmdline):
                    matched = True
                    pid = proc.info.get('pid')
                    name = proc.info.get('name')
                    if confirm:
                        resp = input(f"Do you want to terminate process {name} (PID {pid})? [y/N]: ")
                        if resp.lower() != 'y':
                            continue
                    try:
                        proc.terminate()
                        logging.info(f"Terminated process {name} (PID {pid}).")
                    except Exception as e:
                        logging.error(f"Could not terminate process {name} (PID {pid}): {e}")

                    if delay > 0:
                        logging.info(f"Waiting {delay} ms after terminating {name}.")
                        time.sleep(delay / 1000.0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not matched:
            logging.info(f"Process {proc_info['name']} is not running.")

def start_services(services, confirm, delay=0):
    """Start services from the list, if they're not already running."""
    if os.name != 'nt':
        logging.warning("Service management not implemented for this OS.")
        return

    for svc in services:
        service_name = svc['service_name']
        display_name = svc['display_name']
        current_status = get_service_status(service_name)
        if current_status == 'Running':
            logging.info(f"Service {display_name} ({service_name}) is already running.")
            continue
        if confirm:
            resp = input(f"Do you want to start service {display_name} ({service_name})? [y/N]: ")
            if resp.lower() != 'y':
                continue
        try:
            win32serviceutil.StartService(service_name)
            logging.info(f"Started service {display_name} ({service_name}).")
        except Exception as e:
            logging.error(f"Could not start service {display_name} ({service_name}): {e}")

        if delay > 0:
            logging.info(f"Waiting {delay} ms after starting {display_name}.")
            time.sleep(delay / 1000.0)

def run_processes(processes, confirm, delay=0, fallback_exe=True,
                  skip_cmdline=False, once_only=False, baseline_procs=None):
    """
    Attempt to start processes from the list. Extended logic:
     - If once_only is True, we skip launching if the exe is already in memory.
     - We'll check the system again after launching to see if the process appeared.
       If not, we fallback or log an error.
    """
    if baseline_procs is None:
        baseline_procs = []

    # Let's build a set of all "exe" paths we already see in memory as a baseline
    # (or that we've already launched).
    # We'll refresh it after each successful start.
    known_exes = set()
    # Gather from baseline:
    for bp in baseline_procs:
        if bp.get('exe'):
            known_exes.add(bp['exe'])

    # Get current processes. Also gather from the live system right now (in case baseline is stale).
    current_procs = get_current_processes()
    for cp in current_procs:
        if cp.get('exe'):
            known_exes.add(cp['exe'])

    for proc_info in processes:
        name = proc_info.get('name')
        exe = proc_info.get('exe') or ''
        full_cmdline = proc_info.get('cmdline') or []

        # If skip_cmdline -> launch only [exe]
        chosen_cmd = [exe] if skip_cmdline else full_cmdline

        if not exe:
            logging.warning(f"No exe path for '{name}', cannot run.")
            continue

        # if once_only is set and exe is already in known_exes, skip
        if once_only and exe in known_exes:
            logging.info(f"Skipping '{exe}' because once_only=True and it's already running.")
            continue

        # Attempt to launch
        if confirm:
            resp = input(f"Start process with cmdline '{' '.join(chosen_cmd)}'? [y/N]: ")
            if resp.lower() != 'y':
                continue

        launched_ok = False
        try:
            psutil.Popen(chosen_cmd)
            launched_ok = True
            logging.info(f"Started process with cmdline: {' '.join(chosen_cmd)}.")
        except OSError as e:
            logging.error(f"Could not start process '{name}' with cmd '{chosen_cmd}': {e}")
            # If it's a network path error, we can attempt zone fix
            # Typically WinError=53 or 0x800704b3, but can vary
            if hasattr(e, 'winerror') and e.winerror in [53, 67, 1231, 1203]:
                # Possibly a UNC or mapped drive issue
                # We'll parse out the server name if possible
                # If exe is something like \\server\share\my.exe, we can get the server
                # or if it's c:\, then it's not UNC
                if exe.startswith('\\\\'):
                    server_part = exe.split('\\')[2]  # e.g. \\SERVERNAME => split => ['','', 'SERVERNAME',...]
                    logging.warning(f"Encountered UNC path error. We can add {server_part} to Local Intranet zone.")
                    if confirm:
                        answer = input(f"Do you want to attempt zone fix for {server_part}? [y/N]: ")
                        if answer.lower() == 'y':
                            if attempt_zone_fix(server_part):
                                logging.info("Zone fix done. Please re-run psdelta or the command.")
                            else:
                                logging.warning("Zone fix attempt failed or not possible.")
                else:
                    logging.warning("Network path error but not a clear UNC server. Possibly a mapped drive or subst.")
            elif hasattr(e, 'winerror') and e.winerror == 740 and os.name == 'nt':
                logging.warning(f"Got WinError 740 for '{exe}'. Attempting runas fallback.")
                # Attempt the same full cmd first:
                if shell_execute_runas(exe, chosen_cmd[1:] if len(chosen_cmd) > 1 else None):
                    launched_ok = True
                    logging.info(f"ShellExecuteEx runas launched '{exe}' successfully.")

        if launched_ok:
            time.sleep(delay / 1000.0 if delay else 0)
            new_proc_list = get_current_processes()
            # check if exe is now in the new process list
            if not any(p.get('exe') == exe for p in new_proc_list):
                launched_ok = False
                logging.warning(f"'{exe}' did not appear in memory after waiting {delay}ms.")
            else:
                # Mark it as known
                known_exes.add(exe)

        if fallback_exe and not launched_ok and not skip_cmdline:
            logging.warning(f"Falling back to exe-only for '{name}'.")
            fallback_run(exe, name, confirm, delay, known_exes)

def fallback_run(exe, name, confirm, delay, known_exes):
    if not exe:
        logging.warning(f"No exe found for '{name}', cannot fallback-run.")
        return
    if confirm:
        resp = input(f"Fallback: start process exe '{exe}' (no args)? [y/N]: ")
        if resp.lower() != 'y':
            return
    try:
        psutil.Popen([exe])
        logging.info(f"Fallback started: {exe}")
    except OSError as e:
        logging.error(f"Fallback run failed for {exe}: {e}")
        # If 740 again, try runas:
        if hasattr(e, 'winerror') and e.winerror == 740 and os.name == 'nt':
            logging.warning(f"Fallback got WinError 740 for '{exe}'. Attempting runas fallback.")
            if shell_execute_runas(exe):
                logging.info(f"ShellExecuteEx runas fallback launched '{exe}' successfully.")
        # If it's some other network error, we do not do local copy. We just log it.
        return

    time.sleep(delay / 1000.0 if delay else 0)
    updated_list = get_current_processes()
    if any(p.get('exe') == exe for p in updated_list):
        known_exes.add(exe)
    else:
        logging.warning(f"'{exe}' fallback did not appear in memory after {delay}ms.")

def restart_processes(processes, confirm, delay=0, fallback_exe=True,
                      skip_cmdline=False, once_only=False, baseline_procs=None):
    """Close then run the processes."""
    close_processes(processes, confirm, delay)
    run_processes(processes, confirm, delay, fallback_exe, skip_cmdline,
                  once_only, baseline_procs)

def restart_services(services, confirm, delay=0):
    """Restart the given services via pywin32. Not supported on non-Windows."""
    if os.name != 'nt':
        logging.warning("Service management is not implemented for this OS.")
        return
    for svc in services:
        service_name = svc['service_name']
        display_name = svc['display_name']
        if confirm:
            resp = input(f"Do you want to restart service {display_name} ({service_name})? [y/N]: ")
            if resp.lower() != 'y':
                continue
        try:
            win32serviceutil.RestartService(service_name)
            logging.info(f"Restarted service {display_name} ({service_name}).")
        except Exception as e:
            logging.error(f"Could not restart service {display_name} ({service_name}): {e}")
        if delay > 0:
            logging.info(f"Waiting {delay} ms after restarting service {display_name}.")
            time.sleep(delay / 1000.0)

def detect_and_handle_unc():
    cwd = os.getcwd()
    if (cwd.startswith('\\\\') or cwd.startswith('//')):
        logging.warning(f"You are running psdelta from a UNC path: {cwd}")
        logging.warning("This may cause 'Network path not found' or WinError 53. Consider zone fix or mapping a local drive.")
    elif len(cwd) > 1 and cwd[1] == ':':
        # e.g. "P:\something"
        drive_letter = cwd[:2]
        if drive_is_remote_or_subst(drive_letter):
            logging.warning(f"You are running psdelta from a remote or subst drive: {drive_letter}")
            logging.warning("This can cause WinError 53 or 740 if it points to a UNC path. Consider zone fix or local path.")
    else:
        pass

def parse_args():
    """
    Parse command line arguments.
    """
    parser = argparse.ArgumentParser(
        description='''Process Delta Tool (psdelta): Manage processes and services based on snapshots.

This tool allows you to capture snapshots of running processes and services, compare snapshots to find differences, and perform actions such as starting, stopping, or restarting processes and services based on those differences.  Run `psdelta.py COMMAND -h` for more information on each command.''',
        epilog='''
Use cases include managing applications and services for resource optimization, automating environment setups, or reverting system changes.

Common usage examples:

1. Create a delta of changes in processes and services:
Capture the initial state, make changes (e.g., start or stop applications/services), then capture the modified state and generate a delta.
  psdelta.py delta -o delta.json --wait

2. Perform actions based on a delta:
Use the delta to close processes & stop services terminated between snapshots every 2000ms.
  psdelta.py load -i delta.json -a close -d 2000

To revert the changes captured in the delta:
  psdelta.py load -i delta.json -a close --revert

3. Manage specific applications (e.g., ExpressVPN):
- Stop ExpressVPN services and processes:
  psdelta.py load -i expressvpn_delta.json -a close --include "ExpressVPN*"

- Start ExpressVPN services and processes:
  psdelta.py load -i expressvpn_delta.json -a run --include "ExpressVPN*" --revert

4. Optimize system for resource-intensive applications:
Capture a snapshot after startup, identify unnecessary processes and services, and create a delta to close them before running a resource-intensive application.
  psdelta.py save -o startup_snapshot.json

Then manually stop unwanted processes/services or use system tools
  psdelta.py save -o startup_optimized_snapshot.json 
  psdelta.py compare -s1 startup_snapshot.json -s2 startup_optimized_snapshot.json -o startup_optimization_delta.json 

Or simplified combining the 3 steps into one:
  psdelta.py delta -o startup_optimization_delta.json --wait --save-initial startup_snapshot.json --save-modified startup_optimized_snapshot.json

Last close unnecessary processes and services every 2000ms
  psdelta.py load -a close -d 2000 -i startup_optimization_delta.json

5. Automate environment setup for testing:
Create deltas representing different environments and apply them as needed.
  psdelta.py load -i test_env_delta.json -a run


Other options:

- Use `--include` or `--exclude` to filter specific processes or services.
- Use `--confirm` to prompt for confirmation before performing actions.
- Use `-d` to specify delays between actions.

For more information and advanced usage, please refer to the documentation or use the `-h` option to see all available commands and options.
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Save snapshot
    save_parser = subparsers.add_parser('save', help='Save a snapshot of current processes and services')
    save_parser.add_argument('-o', '--output', required=True, help='Output snapshot file')

    # Load and perform actions
    action_parser = subparsers.add_parser('load', help='Load a snapshot (delta) and perform actions')
    action_parser.add_argument('-i', '--input', required=True, help='Input snapshot/delta file')
    action_parser.add_argument('-a', '--actions', nargs='+', required=True,
                             choices=['close', 'run', 'restart'],
                             help='Actions to perform')
    action_parser.add_argument('-d', '--delay', type=int, default=0,
                             help='Delay between actions (and run timeout) in milliseconds')
    action_parser.add_argument('--include', nargs='+', help='Include only specified processes/services')
    action_parser.add_argument('--exclude', nargs='+', help='Exclude specified processes/services')
    action_parser.add_argument('--confirm', action='store_true', help='Prompt for confirmation before actions')
    action_parser.add_argument('--revert', action='store_true', help='Revert the changes captured in the delta')
    action_parser.add_argument('--fallback-exe', dest='fallback_exe', action='store_true',
                             default=True, help='Fallback to exe-only if full cmdline fails (default: True)')
    action_parser.add_argument('--no-fallback-exe', dest='fallback_exe', action='store_false',
                             help='Disable fallback to exe-only on run failures')
    action_parser.add_argument('--skip-cmdline', action='store_true',
                             help='Skip all parameters and only run the exe (no arguments).')
    action_parser.add_argument('--once-only', action='store_true',
                             help='When skip-cmdline is used, or in general, only launch if exe is not already present.')

    # Compare snapshots
    compare_parser = subparsers.add_parser('compare', help='Compare two snapshots')
    compare_parser.add_argument('-s1', '--snapshot1', required=True, help='First snapshot file')
    compare_parser.add_argument('-s2', '--snapshot2', required=True, help='Second snapshot file')
    compare_parser.add_argument('-o', '--output', required=True, help='Output delta file')
    compare_parser.add_argument('--include', nargs='+', help='Include only specified processes/services')
    compare_parser.add_argument('--exclude', nargs='+', help='Exclude specified processes/services')

    # Delta creation (capture two snapshots, produce a delta in one shot)
    delta_parser = subparsers.add_parser('delta', help='Create a delta between two snapshots')
    delta_parser.add_argument('-o', '--output', required=True, help='Output delta file')
    delta_parser.add_argument('--save-initial', help='File to save the initial snapshot')
    delta_parser.add_argument('--save-modified', help='File to save the modified snapshot')
    delta_parser.add_argument('--wait', action='store_true', help='Wait for user input between snapshots')
    delta_parser.add_argument('--delay', type=int, help='Delay in seconds between snapshots')
    delta_parser.add_argument('--include', nargs='+', help='Include only specified processes/services')
    delta_parser.add_argument('--exclude', nargs='+', help='Exclude specified processes/services')

    # Common arguments
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('-V', '--version', action='version', version=f'%(prog)s {VERSION_STRING}')
    parser.add_argument('--log-file', help='Specify a file to output logs')

    return parser.parse_args()

def apply_filters_to_delta(delta, include, exclude):
    """
    Filter the delta's processes and services according to include/exclude patterns.
    """
    # Apply filters to processes
    delta['processes_started'] = [
        proc for proc in delta.get('processes_started', [])
        if filter_item(proc['name'], include, exclude)
    ]
    delta['processes_terminated'] = [
        proc for proc in delta.get('processes_terminated', [])
        if filter_item(proc['name'], include, exclude)
    ]
    # Apply filters to services
    delta['services'] = [
        svc for svc in delta.get('services', [])
        if filter_item(svc['service_name'], include, exclude)
    ]
    return delta

def main():
    args = parse_args()
    setup_logging(args.verbose, args.log_file)

    detect_and_handle_unc()
    if os.name == 'nt':
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        logging.debug(f"IsUserAnAdmin: {is_admin}")

    if not args.command:
        logging.error("\nusage: psdelta.py [-h] [-v] [--log-file LOG_FILE] {save,load,compare,delta}\n No command provided. Use -h for help.")
        sys.exit(1)

    if args.command == 'save':
        snapshot = {
            'processes': get_current_processes(),
            'services': get_current_services()
        }
        save_snapshot(args.output, snapshot)

    elif args.command == 'load':
        delta = load_snapshot(args.input)
        if args.include or args.exclude:
            delta = apply_filters_to_delta(delta, args.include, args.exclude)

        #baseline current processes (to handle once-only, etc.)
        baseline_procs = get_current_processes()
        perform_actions(
            delta,
            actions=args.actions,
            delay=args.delay,
            confirm=args.confirm,
            revert=args.revert,
            fallback_exe=args.fallback_exe,
            skip_cmdline=args.skip_cmdline,
            once_only=args.once_only,
            baseline_procs=baseline_procs
        )

    elif args.command == 'compare':
        snapshot1 = load_snapshot(args.snapshot1)
        snapshot2 = load_snapshot(args.snapshot2)
        delta = compare_snapshots(snapshot1, snapshot2, args.include, args.exclude)
        with open(args.output, 'w') as f:
            json.dump(delta, f, indent=4)
        logging.info(f"Delta saved to {args.output}")

    elif args.command == 'delta':
        # Capture initial snapshot
        logging.info("Capturing initial snapshot...")
        initial_snapshot = {
            'processes': get_current_processes(),
            'services': get_current_services()
        }
        if args.save_initial:
            save_snapshot(args.save_initial, initial_snapshot)

        # Wait for user input or delay
        if args.wait:
            input("Press Enter to capture the modified snapshot...")
        elif args.delay:
            logging.info(f"Waiting {args.delay} seconds before capturing modified snapshot...")
            time.sleep(args.delay)

        # Capture modified snapshot
        logging.info("Capturing modified snapshot...")
        modified_snapshot = {
            'processes': get_current_processes(),
            'services': get_current_services()
        }
        if args.save_modified:
            save_snapshot(args.save_modified, modified_snapshot)

        # Compute delta
        delta = compare_snapshots(initial_snapshot, modified_snapshot, args.include, args.exclude)
        with open(args.output, 'w') as f:
            json.dump(delta, f, indent=4)
        logging.info(f"Delta saved to {args.output}")

    else:
        logging.error("Invalid command. Use -h for help.")

if __name__ == '__main__':
    main()
