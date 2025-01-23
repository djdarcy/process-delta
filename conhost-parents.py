import psutil
import wmi

# Initialize WMI client
c = wmi.WMI()

def get_parent_chain(pid):
    """Recursively get the parent process chain for a given PID."""
    try:
        process = psutil.Process(pid)
        parent_chain = []

        while process:
            parent_info = {
                "pid": process.pid,
                "name": process.name(),
                "cmdline": ' '.join(process.cmdline())
            }
            parent_chain.append(parent_info)
            
            # Get the parent process
            process = process.parent()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # Stop if the process doesn't exist or if access is denied
        process = None
    
    return parent_chain

# Iterate over all processes named conhost.exe
for process in psutil.process_iter(['pid', 'name']):
    if process.info['name'] == 'conhost.exe':
        pid = process.info['pid']
        
        # Use WMI to get additional details
        query = f"SELECT ParentProcessId, CommandLine FROM Win32_Process WHERE ProcessId = {pid}"
        result = c.query(query)
        
        if result:
            parent_pid = result[0].ParentProcessId
            command_line = result[0].CommandLine
            print(f"Process ID: {pid}")
            print(f"Parent Process ID: {parent_pid}")
            print(f"Command Line: {command_line}")
            print("Tracing Parent Chain:")

            # Trace the parent chain starting with the parent of conhost.exe
            parent_chain = get_parent_chain(parent_pid)
            for parent in parent_chain:
                print(f"  Parent PID: {parent['pid']}, Name: {parent['name']}, Command Line: {parent['cmdline']}")
                
            print("-------------------------------------------")
