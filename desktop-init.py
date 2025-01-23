from __future__ import print_function
import pyWinVirtualDesktop

import os
import subprocess, shlex
import psutil
import win32api, win32pdh, win32com.client
import time
import struct


'''
Ideas for the future:
Check if a process is running in another virtual desktop like OneNote. Perhaps through the shortcut setup a naming convention that will
tell this script to pull it to this window before trying to continue down the list of items to load?
'''


#Testing code for how to get process info about a virtual desktop
#
#StackOverflow:         https://stackoverflow.com/questions/57149456/how-to-implement-windows-10-ivirtualdesktopmanager-interface-in-python
#Functioning:           https://github.com/ipaleka/pyWinVirtualDesktop
#Improvements to merge: https://github.com/kdschlosser/pyWinVirtualDesktop
#Additional notes:      https://github.com/DanEdens/Virtual_Desktops_Plugin/issues/1
def IsShortcutAlreadyRunning(filename):
    shortcut_basename = os.path.splitext(filename)[0].lower()
    for desktop in pyWinVirtualDesktop:
        #print('DESKTOP ID:', desktop.id)
        #print('DESKTOP IS ACTIVE:', desktop.is_active)
        #print('DESKTOP WINDOWS:')
        if(desktop.is_active):
            for window in desktop:
                if(window.is_on_active_desktop):
                    #print('    HANDLE:', window.id)
                    #print('    CAPTION:', window.text)
                    #print('    PROCESS NAME:', str(window.process_name))
                    #print('    ON ACTIVE DESKTOP:', window.is_on_active_desktop)
                    #print('\n')
                    #print( str(shortcut_basename.lower() in str(window.process_name).lower()) + " : " + shortcut_basename.lower() + " , " + str(window.process_name).lower() )
                    process_name = str(window.process_name).lower()
                    #https://www.devguru.com/content/technologies/wsh/objects-wshshortcut.html
                    shortcut_obj = shell.CreateShortCut(filename)
                    
                    #https://stackoverflow.com/questions/397125/reading-the-target-of-a-lnk-file-in-python
                    shortcut_targetname = os.path.basename(shortcut_obj.Targetpath.lower())
                    shortcut_targetname = os.path.splitext(shortcut_targetname)[0]
                    shortcut_arguments = shortcut_obj.Arguments
                    allow_multiple_processes = True if ('--' in filename) else False

                    if(shortcut_basename in process_name or 
                       shortcut_basename in shortcut_arguments or
                       ((not allow_multiple_processes) and shortcut_targetname in process_name)):
                        return True
        #else:
            #print("INACTIVE DESKTOP PROCESSES:")
            #for window in desktop:
                #print('    HANDLE:', window.id)
                #print('    CAPTION:', window.text)
                #print('    PROCESS NAME:', str(window.process_name))
                #print('    ON ACTIVE DESKTOP:', window.is_on_active_desktop)
                #print('\n')
                #print( str(shortcut_basename.lower() in str(window.process_name).lower()) + " : " + shortcut_basename.lower() + " , " + str(window.process_name).lower() )
    return False



shell = win32com.client.Dispatch("WScript.Shell")
#print(os.getcwd())
os.chdir(os.getcwd() + "/Desktop-Startup")
#print(os.getcwd())
directory = os.getcwd()
for filename in os.listdir(directory):
    if filename.endswith(".lnk"):
        args = ['explorer.exe', filename]
        basename = os.path.splitext(filename)[0]
        print(os.path.join(directory, filename))
            
        if(not IsShortcutAlreadyRunning(filename)): 
            counter = 0
            print("Running: " + basename)
            proc = subprocess.Popen(args, shell=False, stdin=None, stdout=None, stderr=None, close_fds=True)
            while(not IsShortcutAlreadyRunning(filename)):
                if(counter > 2):        #DUSTIN: Hack to allow duplicate lnks (need a better approach xml? manually parse lnk for executable?)
                    break
                counter += 1
                time.sleep(1)
            time.sleep(1)
            #move_to_desktop
    else:
        continue

# https://stackoverflow.com/questions/181169
#1/running-an-outside-program-executable-in-python

#subprocess.run(
#)