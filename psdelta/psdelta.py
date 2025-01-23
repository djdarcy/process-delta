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

VERSION_STRING = "0.0.1.0"

#Version 0.1.0 - Basic functionality for capturing snapshots, comparing, and performing actions based on differences
#Version 0.0.7 - Added support for sorting services based on dependencies in Windows
#Version 0.0.6 - Added support for saving initial and modified snapshots in delta creation
#Version 0.0.5 - Added support for capturing snapshots with delays and waiting for user input
#Version 0.0.4 - Added support for reverting changes captured in a delta
#Version 0.0.3 - Added support for delays between actions and confirmation prompts
#Version 0.0.2 - Added support for filtering processes and services based on include/exclude patterns
#Version 0.0.1 - Added support for Windows services and actions to start, stop, or restart services

if os.name == 'nt':
    import win32service
    import win32serviceutil
    import win32api
    import win32con
    import pywintypes
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
    services = []
    if os.name == 'nt':
        # Windows-specific service handling
        services = get_windows_services()
    else:
        # Placeholder for Unix-like systems
        pass
    return services

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
    exclude.extend(DEFAULT_EXCLUDES)
    if include:
        if not any(fnmatch.fnmatch(name, pattern) for pattern in include):
            return False
    if exclude:
        if any(fnmatch.fnmatch(name, pattern) for pattern in exclude):
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

def compare_processes(current_processes, processes_to_check):
    current_uids = {create_process_uid(proc) for proc in current_processes}
    processes_uids = {create_process_uid(proc) for proc in processes_to_check}
    # Return the UIDs of processes that are present in both
    return current_uids & processes_uids

def get_service_status(service_name):
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
    sorted_services = []
    svc_dict = {svc['service_name']: svc for svc in services}
    for svc_name in sorted_service_names:
        sorted_services.append(svc_dict[svc_name])

    return sorted_services

def perform_actions(delta, actions, delay=0, confirm=False, revert=False):
    for action in actions:
        if action == 'close':
            if revert:
                # Stop services first
                services_to_stop = [
                    svc for svc in delta.get('services', [])
                    if svc.get('status_before') == 'Stopped'
                ]
                stop_services(services_to_stop, confirm, delay)
                if delay > 0:
                    logging.info(f"Waiting for {delay} milliseconds after stopping services.")
                    time.sleep(delay / 1000)
                # Close processes that have started
                close_processes(delta.get('processes_started', []), confirm, delay)
            else:
                # Stop services first
                services_to_stop = [
                    svc for svc in delta.get('services', [])
                    if svc.get('status_after') == 'Stopped'
                ]
                stop_services(services_to_stop, confirm, delay)
                if delay > 0:
                    logging.info(f"Waiting for {delay} milliseconds after stopping services.")
                    time.sleep(delay / 1000)
                # Close processes that have terminated
                close_processes(delta.get('processes_terminated', []), confirm, delay)
        elif action == 'run':
            if revert:
                # Start services first
                services_to_start = [
                    svc for svc in delta.get('services', [])
                    if svc.get('status_before') == 'Running'
                ]
                start_services(services_to_start, confirm, delay)
                if delay > 0:
                    logging.info(f"Waiting for {delay} milliseconds after starting services.")
                    time.sleep(delay / 1000)
                # Start processes that have terminated
                run_processes(delta.get('processes_terminated', []), confirm, delay)
            else:
                # Start services first
                services_to_start = [
                    svc for svc in delta.get('services', [])
                    if svc.get('status_after') == 'Running'
                ]
                start_services(services_to_start, confirm, delay)
                if delay > 0:
                    logging.info(f"Waiting for {delay} milliseconds after starting services.")
                    time.sleep(delay / 1000)
                # Start processes that have started
                run_processes(delta.get('processes_started', []), confirm, delay)
        elif action == 'restart':
            # Restart services first
            services_to_restart = delta.get('services', [])
            restart_services(services_to_restart, confirm, delay)
            if delay > 0:
                logging.info(f"Waiting for {delay} milliseconds after restarting services.")
                time.sleep(delay / 1000)
            # Restart processes that have changed
            processes_to_restart = delta.get('processes_started', []) + delta.get('processes_terminated', [])
            restart_processes(processes_to_restart, confirm, delay)
        if delay > 0:
            logging.info(f"Waiting for {delay} milliseconds before next action.")
            time.sleep(delay / 1000)

def stop_services(services, confirm, delay=0):
    if os.name != 'nt':
        logging.warning("Service management is not implemented for this OS.")
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
            time.sleep(delay / 1000)

def close_processes(processes, confirm, delay=0):
    # Get current processes
    current_processes = list(psutil.process_iter(['pid', 'name', 'exe', 'cmdline']))
    for proc_info in processes:
        exe = proc_info.get('exe') or ''
        cmdline = proc_info.get('cmdline') or []
        matched = False
        for proc in current_processes:
            try:
                if proc.info.get('exe') == exe and proc.info.get('cmdline') == cmdline:
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
                        logging.info(f"Waiting for {delay} milliseconds after terminating process {name}.")
                        time.sleep(delay / 1000)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not matched:
            logging.info(f"Process {proc_info['name']} is not running.")

def start_services(services, confirm, delay=0):
    if os.name != 'nt':
        logging.warning("Service management is not implemented for this OS.")
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
            logging.info(f"Waiting for {delay} milliseconds after starting service {display_name}.")
            time.sleep(delay / 1000)

def run_processes(processes, confirm, delay=0):
    # Get current processes
    current_processes = list(psutil.process_iter(['exe', 'cmdline']))
    running_processes = set()
    for proc in current_processes:
        exe = proc.info.get('exe') or ''
        cmdline = proc.info.get('cmdline') or []
        uid = f"{exe}|{' '.join(cmdline)}"
        running_processes.add(uid)
    for proc_info in processes:
        exe = proc_info.get('exe') or ''
        cmdline = proc_info.get('cmdline') or []
        uid = f"{exe}|{' '.join(cmdline)}"
        if uid in running_processes:
            logging.info(f"Process {proc_info['name']} is already running.")
            continue
        if not cmdline:
            continue
        if confirm:
            resp = input(f"Do you want to start process {' '.join(cmdline)}? [y/N]: ")
            if resp.lower() != 'y':
                continue
        try:
            psutil.Popen(cmdline)
            logging.info(f"Started process {' '.join(cmdline)}.")
        except Exception as e:
            logging.error(f"Could not start process {' '.join(cmdline)}: {e}")
        if delay > 0:
            logging.info(f"Waiting for {delay} milliseconds after starting process {' '.join(cmdline)}.")
            time.sleep(delay / 1000)

def restart_processes(processes, confirm, delay=0):
    close_processes(processes, confirm, delay)
    run_processes(processes, confirm, delay)

def restart_services(services, confirm, delay=0):
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
            logging.info(f"Waiting for {delay} milliseconds after restarting service {display_name}.")
            time.sleep(delay / 1000)

def parse_args():
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
    action_parser = subparsers.add_parser('load', help='Load a snapshot and perform actions')
    action_parser.add_argument('-i', '--input', required=True, help='Input snapshot file')
    action_parser.add_argument('-a', '--actions', nargs='+', required=True,
                            choices=['close', 'run', 'restart'], help='Actions to perform')
    action_parser.add_argument('-d', '--delay', type=int, default=0, help='Delay between actions in milliseconds')
    action_parser.add_argument('--include', nargs='+', help='Include only specified processes/services')
    action_parser.add_argument('--exclude', nargs='+', help='Exclude specified processes/services')
    action_parser.add_argument('--confirm', action='store_true', help='Prompt for confirmation before actions')
    action_parser.add_argument('--revert', action='store_true', help='Revert the changes captured in the delta')

    # Compare snapshots
    compare_parser = subparsers.add_parser('compare', help='Compare two snapshots')
    compare_parser.add_argument('-s1', '--snapshot1', required=True, help='First snapshot file')
    compare_parser.add_argument('-s2', '--snapshot2', required=True, help='Second snapshot file')
    compare_parser.add_argument('-o', '--output', required=True, help='Output delta file')
    compare_parser.add_argument('--include', nargs='+', help='Include only specified processes/services')
    compare_parser.add_argument('--exclude', nargs='+', help='Exclude specified processes/services')

    # Delta creation
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
    parser.add_argument('--log-file', help='Specify a file to output logs')

    return parser.parse_args()

def apply_filters_to_delta(delta, include, exclude):
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

    if not args.command:
        logging.error("\nusage: psdelta.py [-h] [-v] [--log-file LOG_FILE] {save,load,compare,delta}\n No command provided. Use -h for help.")
        sys.exit(1)

    setup_logging(args.verbose, args.log_file)

    if args.command == 'save':
        snapshot = {
            'processes': get_current_processes(),
            'services': get_current_services()
        }
        save_snapshot(args.output, snapshot)

    elif args.command == 'load':
        snapshot_file = args.input
        actions = args.actions
        delay = args.delay
        include = args.include
        exclude = args.exclude
        confirm = args.confirm
        revert = args.revert

        delta = load_snapshot(snapshot_file)
        if include or exclude:
            # Apply filters to delta data
            delta = apply_filters_to_delta(delta, include, exclude)
        perform_actions(delta, actions, delay, confirm, revert)

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
            logging.info(f"Waiting for {args.delay} seconds...")
            time.sleep(args.delay)
        else:
            # Default behavior: immediate snapshot
            pass

        # Capture modified snapshot
        logging.info("Capturing modified snapshot...")
        modified_snapshot = {
            'processes': get_current_processes(),
            'services': get_current_services()
        }
        if args.save_modified:
            save_snapshot(args.save_modified, modified_snapshot)

        # Compute delta
        delta = compare_snapshots(
            initial_snapshot, modified_snapshot, args.include, args.exclude
        )
        with open(args.output, 'w') as f:
            json.dump(delta, f, indent=4)
        logging.info(f"Delta saved to {args.output}")

    else:
        logging.error("No valid command provided. Use -h for help.")


if __name__ == '__main__':
    main()
