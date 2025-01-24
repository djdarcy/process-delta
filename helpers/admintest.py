import ctypes
is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
print("Am I admin?", is_admin)
