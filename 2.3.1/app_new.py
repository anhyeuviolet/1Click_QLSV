import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import subprocess
import threading
import time
import os
import stat
import logging
import json
from datetime import datetime, timedelta

class ProcessRestarterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Server JX Linux")
        self.root.geometry("660x630")
        
        # Set the path to jx_new.sh script
        # Use the jx_new.sh in the same directory as this script
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.BASH_SCRIPT = os.path.join(current_dir, "jx_new.sh")
        
        # Ensure jx_new.sh is executable
        if os.path.exists(self.BASH_SCRIPT):
            self._make_executable(self.BASH_SCRIPT)
        
        # --- Configuration ---
        self.config_path = os.path.join(os.path.expanduser("~"), ".process_restarter_config.json")
        self.server_config_path = '/root/.quanlyserver.json'
        self.log_file = os.path.join(os.path.expanduser("~"), f"process_restarter_{datetime.now():%Y-%m-%d}.log")
        self.check_interval = 5  # seconds

        # --- State Variables ---
        self.monitoring = threading.Event()
        self.monitor_thread = None
        self.process = None
        self.start_time = None
        self.last_runtime_seconds = 0

        # --- UI Variables ---
        self.launch_script = tk.StringVar()
        self.process_name = tk.StringVar()
        self.current_runtime_str = tk.StringVar(value="00:00:00")
        self.last_runtime_str = tk.StringVar(value="00:00:00")
        self.monitor_mode = tk.StringVar(value='automatic')
        self.restart_interval = tk.StringVar(value='60')
        self.restart_delay = tk.StringVar(value='5')
        self.successful_restarts = tk.IntVar(value=0)
        self.failed_restarts = tk.IntVar(value=0)
        self.unexpected_shutdowns = tk.IntVar(value=0)

        # --- Server Management Variables ---
        self.server_config = self._load_server_config()
        self.network_interfaces = self._get_all_network_interfaces()
        self.selected_ip = tk.StringVar()
        
        # Set default IP and MAC
        if 'server_ip' not in self.server_config and self.network_interfaces:
            self.server_config['server_ip'] = self.network_interfaces[0]['ip']
            self.server_config['server_mac'] = self.network_interfaces[0]['mac']
        elif 'server_ip' not in self.server_config:
            self.server_config['server_ip'] = self._get_lan_ip()
            self.server_config['server_mac'] = ""
            
        if 'directory' not in self.server_config:
            self.server_config['directory'] = "/home/jxser"
        
        self.processes = {
            "PaySys": {"status": False},
            "RelayServer": {"status": False},
            "goddess_y": {"status": False},
            "bishop_y": {"status": False},
            "s3relay_y": {"status": False},
            "jx_linux_y": {"status": False}
        }
        
        self.hidden_processes = {
            "MySQL": {"status": False},
            "MSSQL": {"status": False}
        }
        
        self.server_ui = {}
        
        # Scheduling variables
        self.scheduled_tasks = []  # List of {time: "HH:MM", action: "start_all"|"stop_all", enabled: bool}

        self.setup_logging()
        self.load_config()
        self.load_scheduled_tasks()
        self.setup_tabbed_ui()
        self.update_runtime_display()
        self._start_server_monitoring()
        self._start_schedule_monitoring()

    def _make_executable(self, file_path):
        """Make a file executable"""
        if os.path.isfile(file_path):
            mode = os.stat(file_path).st_mode
            mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            os.chmod(file_path, mode)

    def _get_all_network_interfaces(self):
        """Get all available network interfaces with their IPs and MACs"""
        try:
            result = subprocess.run(["ip", "-o", "-4", "addr", "show"], 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            interfaces = []
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 4:
                        interface = parts[1]
                        if interface == 'lo' or 'docker' in interface:
                            continue
                        
                        ip_with_prefix = parts[3]
                        ip = ip_with_prefix.split('/')[0]
                        
                        mac_result = subprocess.run(["cat", f"/sys/class/net/{interface}/address"], 
                                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        mac = mac_result.stdout.strip().upper().replace(':', '-') if mac_result.returncode == 0 else ""
                        
                        interfaces.append({
                            "interface": interface,
                            "ip": ip,
                            "mac": mac
                        })
            
            return interfaces
        except Exception as e:
            logging.error(f"Error getting network interfaces: {e}")
            return []

    def _get_lan_ip(self):
        """Get LAN IP address"""
        try:
            result = subprocess.run(["bash", "-c", "ip -4 -br a | grep -v lo | grep -v docker | awk '{print $3}' | cut -d'/' -f1"], 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
            return "127.0.0.1"
        except Exception:
            return "127.0.0.1"

    def _load_server_config(self):
        """Load server configuration"""
        try:
            if os.path.exists(self.server_config_path):
                with open(self.server_config_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load server config: {e}")
        return {"directory": "/home/jxser"}

    def _save_server_config(self):
        """Save server configuration"""
        try:
            with open(self.server_config_path, 'w') as f:
                json.dump(self.server_config, f)
        except Exception as e:
            logging.error(f"Failed to save server config: {e}")

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler()
            ]
        )

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    self.launch_script.set(config.get("launch_script", ""))
                    self.process_name.set(config.get("process_name", ""))
                    logging.info("Loaded last configuration.")
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Failed to load config file: {e}")

    def save_config(self):
        config = {
            "launch_script": self.launch_script.get(),
            "process_name": self.process_name.get()
        }
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=4)
                logging.info("Configuration saved.")
        except IOError as e:
            logging.error(f"Failed to save config file: {e}")

    def setup_tabbed_ui(self):
        """Setup tabbed interface"""
        # Create notebook (tabbed interface)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create tabs
        self.server_tab = tk.Frame(self.notebook)
        self.restarter_tab = tk.Frame(self.notebook)
        
        self.notebook.add(self.server_tab, text="General")
        self.notebook.add(self.restarter_tab, text="Process Restarter")
        
        # Setup each tab
        self.setup_server_tab()
        self.setup_restarter_tab()


    def setup_restarter_tab(self):
        """Setup the Process Restarter tab (original functionality)"""
        main_frame = tk.Frame(self.restarter_tab, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Configuration Frame ---
        config_frame = tk.LabelFrame(main_frame, text="Configuration", padx=10, pady=10)
        config_frame.pack(fill=tk.X, expand=True, pady=5)

        tk.Label(config_frame, text="Script to run:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.script_entry = tk.Entry(config_frame, textvariable=self.launch_script, width=40)
        self.script_entry.grid(row=0, column=1, sticky=tk.EW, padx=5)
        tk.Button(config_frame, text="Browse...", command=self.browse_script).grid(row=0, column=2)

        tk.Label(config_frame, text="Process name:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.process_entry = tk.Entry(config_frame, textvariable=self.process_name, width=40)
        self.process_entry.grid(row=1, column=1, sticky=tk.EW, padx=5)
        config_frame.columnconfigure(1, weight=1)

        # --- Start Options Frame ---
        self.start_options_frame = tk.LabelFrame(main_frame, text="Monitoring Mode", padx=10, pady=10)
        self.start_options_frame.pack(fill=tk.X, expand=True, pady=5)
        
        tk.Radiobutton(
            self.start_options_frame,
            text="Automatic Restart (if process stops)",
            variable=self.monitor_mode,
            value='automatic',
            command=self.toggle_restart_options
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W)

        tk.Radiobutton(
            self.start_options_frame,
            text="Scheduled Restart with Failure Recovery (Hybrid)",
            variable=self.monitor_mode,
            value='hybrid',
            command=self.toggle_restart_options
        ).grid(row=1, column=0, columnspan=4, sticky=tk.W)
        
        scheduled_frame = tk.Frame(self.start_options_frame)
        scheduled_frame.grid(row=2, column=0, columnspan=4, sticky=tk.W)

        tk.Radiobutton(
            scheduled_frame,
            text="Scheduled-Only Restart every",
            variable=self.monitor_mode,
            value='scheduled',
            command=self.toggle_restart_options
        ).pack(side=tk.LEFT)

        self.interval_spinbox = tk.Spinbox(
            scheduled_frame, from_=1, to=1440, textvariable=self.restart_interval, width=5)
        self.interval_spinbox.pack(side=tk.LEFT, padx=5)
        tk.Label(scheduled_frame, text="minutes, with a").pack(side=tk.LEFT)
        
        self.delay_spinbox = tk.Spinbox(
            scheduled_frame, from_=1, to=300, textvariable=self.restart_delay, width=4)
        self.delay_spinbox.pack(side=tk.LEFT, padx=5)
        tk.Label(scheduled_frame, text="second delay").pack(side=tk.LEFT)

        self.toggle_restart_options()

        # --- Status & Runtime Frame ---
        stats_frame = tk.LabelFrame(main_frame, text="Status & Stats", padx=10, pady=10)
        stats_frame.pack(fill=tk.X, expand=True, pady=5)
        self.status_label = tk.Label(stats_frame, text="IDLE", font=("Helvetica", 14, "bold"), fg="red")
        self.status_label.pack()

        details_frame = tk.Frame(stats_frame)
        details_frame.pack(pady=5)
        tk.Label(details_frame, text="Current Runtime:").grid(row=0, column=0, sticky=tk.E)
        tk.Label(details_frame, textvariable=self.current_runtime_str).grid(row=0, column=1, sticky=tk.W, padx=5)
        tk.Label(details_frame, text="Last Runtime:").grid(row=1, column=0, sticky=tk.E)
        tk.Label(details_frame, textvariable=self.last_runtime_str).grid(row=1, column=1, sticky=tk.W, padx=5)
        tk.Label(details_frame, text="Successful Restarts:").grid(row=2, column=0, sticky=tk.E)
        tk.Label(details_frame, textvariable=self.successful_restarts).grid(row=2, column=1, sticky=tk.W, padx=5)
        tk.Label(details_frame, text="Failed Restarts:").grid(row=3, column=0, sticky=tk.E)
        tk.Label(details_frame, textvariable=self.failed_restarts).grid(row=3, column=1, sticky=tk.W, padx=5)
        tk.Label(details_frame, text="Unexpected Shutdowns:").grid(row=4, column=0, sticky=tk.E)
        tk.Label(details_frame, textvariable=self.unexpected_shutdowns).grid(row=4, column=1, sticky=tk.W, padx=5)

        # --- Control Buttons ---
        button_frame = tk.Frame(main_frame, pady=5)
        button_frame.pack(fill=tk.X, expand=True)
        self.start_button = tk.Button(button_frame, text="Start Monitoring", command=self.start_monitoring, bg="#4CAF50", fg="white")
        self.start_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.stop_button = tk.Button(button_frame, text="Stop Monitoring", command=self.stop_monitoring, state=tk.DISABLED, bg="#f44336", fg="white")
        self.stop_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(button_frame, text="View Log", command=self.view_log).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    def setup_server_tab(self):
        """Setup the Server Management tab (from app.py)"""
        # Create scrollable canvas
        canvas = tk.Canvas(self.server_tab)
        scrollbar = tk.Scrollbar(self.server_tab, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Server IP Selection
        ip_frame = tk.LabelFrame(scrollable_frame, text="Server Configuration", padx=10, pady=10)
        ip_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(ip_frame, text="Server IP:", font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky=tk.W)
        
        ip_values = [interface['ip'] for interface in self.network_interfaces]
        
        if len(ip_values) <= 1:
            ip_value = ip_values[0] if ip_values else self._get_lan_ip()
            self.selected_ip.set(ip_value)
            self.server_config['server_ip'] = ip_value
            
            for interface in self.network_interfaces:
                if interface['ip'] == ip_value:
                    self.server_config['server_mac'] = interface['mac']
                    break
            
            self._save_server_config()
            tk.Label(ip_frame, text=ip_value, font=("Helvetica", 10)).grid(row=0, column=1, sticky=tk.W, padx=10)
        else:
            if 'server_ip' in self.server_config and self.server_config['server_ip'] in ip_values:
                self.selected_ip.set(self.server_config['server_ip'])
            else:
                self.selected_ip.set(ip_values[0])
            
            ip_combo = ttk.Combobox(ip_frame, textvariable=self.selected_ip, values=ip_values, state="readonly", width=20)
            ip_combo.grid(row=0, column=1, sticky=tk.W, padx=10)
            ip_combo.bind("<<ComboboxSelected>>", self._on_ip_selected)

        # Server Directory
        tk.Label(ip_frame, text="Server Path:", font=("Helvetica", 10, "bold")).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.dir_label = tk.Label(ip_frame, text=self.server_config["directory"], fg="#1f73b7")
        self.dir_label.grid(row=1, column=1, sticky=tk.W, padx=10)
        tk.Button(ip_frame, text="Change", command=self._change_server_directory).grid(row=1, column=2, padx=5)

       # --- Main Control Buttons ---
        # Lấy màu nền hệ thống để loại bỏ khung viền
        system_bg = self.root.cget('bg') 

        # 1. HÀNG 1: Start All và Stop All
        row1_frame = tk.Frame(scrollable_frame, bg=system_bg)
        row1_frame.pack(fill=tk.X, padx=15, pady=(10, 5))
        
        # Sử dụng uniform='group1' để ép 2 cột bằng nhau
        row1_frame.columnconfigure(0, weight=1, uniform='group1')
        row1_frame.columnconfigure(1, weight=1, uniform='group1')

        tk.Button(row1_frame, text="▶  Bật Server", command=lambda: self._server_action("start_all"), 
                  bg="#1e88e5", fg="white", height=2, font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT).grid(row=0, column=0, padx=5, sticky="ew")
        
        tk.Button(row1_frame, text="⏹  Tắt Server", command=lambda: self._server_action("stop_all"), 
                  bg="#e53935", fg="white", height=2, font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT).grid(row=0, column=1, padx=5, sticky="ew")

        # 2. HÀNG 2: Backup DB, Restore DB, Tài Khoản, Backupdaemon
        row2_frame = tk.Frame(scrollable_frame, bg=system_bg)
        row2_frame.pack(fill=tk.X, padx=15, pady=(5, 10))

        # Sử dụng uniform='group2' để ép 4 cột bằng nhau
        for i in range(4):
            row2_frame.columnconfigure(i, weight=1, uniform='group2')

        btn_style = {"height": 2, "relief": tk.FLAT, "font": ('Segoe UI', 9)}

        tk.Button(row2_frame, text="📂 Backup DB", command=lambda: self._server_action("backup"), 
                  bg="#43a047", fg="white", **btn_style).grid(row=0, column=0, padx=5, sticky="ew")
        
        tk.Button(row2_frame, text="🔄 Restore DB", command=self._restore_backup_dialog, 
                  bg="#fb8c00", fg="white", **btn_style).grid(row=0, column=1, padx=5, sticky="ew")

        tk.Button(row2_frame, text="👤 Tài Khoản", command=self._open_users_manager, 
                  bg="#8e24aa", fg="white", **btn_style).grid(row=0, column=2, padx=5, sticky="ew")

        tk.Button(row2_frame, text="🛡️ Backupdaemon", command=lambda: self._exec_command_with_terminal(["backup_bxh"]), 
                  bg="#00897b", fg="white", **btn_style).grid(row=0, column=3, padx=5, sticky="ew")

        # Processes Frame
        processes_frame = tk.LabelFrame(scrollable_frame, text="Server Processes", padx=10, pady=10, bg="#ececec")
        processes_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        row_num = 0
        for process_name in self.processes:
            tk.Label(processes_frame, text=process_name, font=("Helvetica", 10, "bold"), 
                     bg="#ececec").grid(row=row_num, column=0, sticky=tk.W, pady=5, padx=5)
            
            status_label = tk.Label(processes_frame, text="Stopped", fg="red", bg="#ececec")
            status_label.grid(row=row_num, column=1, sticky=tk.W, padx=10)
            self.server_ui[process_name] = {"status_label": status_label}
            
            btn_frame = tk.Frame(processes_frame, bg="#ececec")
            btn_frame.grid(row=row_num, column=2, sticky=tk.E, padx=5)
            
            start_btn = tk.Button(btn_frame, text="Start", 
                                  command=lambda p=process_name: self._server_action("start", p),
                                  bg="#1f73b7", fg="white", width=6)
            start_btn.pack(side=tk.LEFT, padx=2)
            
            stop_btn = tk.Button(btn_frame, text="Stop", 
                                 command=lambda p=process_name: self._server_action("stop", p),
                                 bg="#f44336", fg="white", width=6)
            stop_btn.pack(side=tk.LEFT, padx=2)
            
            row_num += 1
        
        # Database Status Frame
        db_frame = tk.LabelFrame(scrollable_frame, text="Database Status", padx=10, pady=10)
        db_frame.pack(fill=tk.X, padx=10, pady=5)
        
        for db_name in ["MSSQL", "MySQL"]:
            tk.Label(db_frame, text=db_name, font=("Helvetica", 10, "bold")).grid(
                row=list(self.hidden_processes.keys()).index(db_name), column=0, sticky=tk.W, pady=5)
            
            status_label = tk.Label(db_frame, text="Stopped", fg="red")
            status_label.grid(row=list(self.hidden_processes.keys()).index(db_name), column=1, sticky=tk.W, padx=10)
            self.server_ui[db_name] = {"status_label": status_label}

        # Tools Frame
        #tools_frame = tk.LabelFrame(scrollable_frame, text="Server Tools", padx=10, pady=10)
        #tools_frame.pack(fill=tk.X, padx=10, pady=5)
        
        #tk.Button(tools_frame, text="Start Databases", command=lambda: self._exec_command(["startDB"]),
        #          width=20).grid(row=0, column=0, padx=5, pady=5)
        #tk.Button(tools_frame, text="Update Server (Patch)", command=lambda: self._server_action("patch"),
        #          width=20).grid(row=0, column=1, padx=5, pady=5)
        #tk.Button(tools_frame, text="Backup Server Files", command=lambda: self._server_action("backup_server"),
        #          width=20).grid(row=1, column=0, padx=5, pady=5)

        # Scheduling Frame
        schedule_frame = tk.LabelFrame(scrollable_frame, text="Server Schedule (Daily Recurring)", padx=10, pady=10)
        schedule_frame.pack(fill=tk.X, padx=10, pady=5)
        
        info_frame = tk.Frame(schedule_frame)
        info_frame.pack(fill=tk.X, pady=(0,5))
        tk.Label(info_frame, text="⏰ Schedule automatic Start/Stop times that repeat every day:", 
                 font=("Helvetica", 9, "italic")).pack(anchor=tk.W)
        tk.Label(info_frame, text="   • Schedules execute daily at the specified time", 
                 font=("Helvetica", 8), fg="#555").pack(anchor=tk.W)
        tk.Label(info_frame, text="   • Automatically reset at midnight for next day", 
                 font=("Helvetica", 8), fg="#555").pack(anchor=tk.W)
        
        # Add new schedule controls
        add_frame = tk.Frame(schedule_frame)
        add_frame.pack(fill=tk.X, pady=5)
        
        # Show current system time
        current_time_label = tk.Label(add_frame, text="", fg="#1f73b7", font=("Helvetica", 9, "bold"))
        current_time_label.pack(side=tk.LEFT, padx=5)
        self.schedule_current_time_label = current_time_label
        
        tk.Label(add_frame, text="Set:").pack(side=tk.LEFT, padx=(10, 5))
        
        # Get current time for smart defaults
        now = datetime.now()
        current_hour_12 = now.hour if now.hour <= 12 else now.hour - 12
        if current_hour_12 == 0:
            current_hour_12 = 12
        current_minute = now.minute
        current_ampm = "AM" if now.hour < 12 else "PM"
        
        # Hour spinbox with smart default value (current time)
        hour_var = tk.StringVar(value=f"{current_hour_12:02d}")
        self.schedule_hour = tk.Spinbox(add_frame, from_=1, to=12, width=3, format="%02.0f", textvariable=hour_var)
        self.schedule_hour.pack(side=tk.LEFT)
        tk.Label(add_frame, text=":").pack(side=tk.LEFT)
        
        # Minute spinbox with smart default value (current time)
        minute_var = tk.StringVar(value=f"{current_minute:02d}")
        self.schedule_minute = tk.Spinbox(add_frame, from_=0, to=59, width=3, format="%02.0f", textvariable=minute_var)
        self.schedule_minute.pack(side=tk.LEFT)
        
        # AM/PM with smart default (matches current time)
        self.schedule_ampm = ttk.Combobox(add_frame, values=["AM", "PM"], state="readonly", width=4)
        self.schedule_ampm.set(current_ampm)
        self.schedule_ampm.pack(side=tk.LEFT, padx=5)
        
        tk.Label(add_frame, text="Action:").pack(side=tk.LEFT, padx=5)
        # --- UPDATE: Added "Backup" to Combobox ---
        self.schedule_action = ttk.Combobox(add_frame, values=["Start All", "Stop All", "Backup"], state="readonly", width=10)
        self.schedule_action.set("Start All")
        self.schedule_action.pack(side=tk.LEFT, padx=5)
        
        tk.Button(add_frame, text="Add Schedule", command=self._add_schedule, bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=5)
        
        # Schedule list
        self.schedule_listbox_frame = tk.Frame(schedule_frame)
        self.schedule_listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.schedule_listbox = tk.Listbox(self.schedule_listbox_frame, height=5)
        self.schedule_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        schedule_scroll = tk.Scrollbar(self.schedule_listbox_frame, orient=tk.VERTICAL, command=self.schedule_listbox.yview)
        schedule_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.schedule_listbox.config(yscrollcommand=schedule_scroll.set)
        
        schedule_btn_frame = tk.Frame(schedule_frame)
        schedule_btn_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(schedule_btn_frame, text="Remove Selected", command=self._remove_schedule, bg="#f44336", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(schedule_btn_frame, text="Clear All", command=self._clear_schedules, bg="#ff9800", fg="white").pack(side=tk.LEFT, padx=5)
        
        self._refresh_schedule_list()

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _on_ip_selected(self, event):
        """Handle IP selection change"""
        selected_ip = self.selected_ip.get()
        for interface in self.network_interfaces:
            if interface['ip'] == selected_ip:
                self.server_config['server_ip'] = selected_ip
                self.server_config['server_mac'] = interface['mac']
                self._save_server_config()
                break

    def _change_server_directory(self):
        """Change server directory"""
        folder_selected = filedialog.askdirectory(initialdir=self.server_config["directory"])
        if folder_selected:
            self.server_config["directory"] = folder_selected
            self.dir_label.config(text=folder_selected)
            self._save_server_config()

    # --- NEW: Restore Backup Dialog Method ---
    def _restore_backup_dialog(self):
        """Open file dialog for restore"""
        file_path = filedialog.askopenfilename(
            title="Choose Backup File",
            filetypes=(("Backup files", "*.sql *.bak"), ("All files", "*.*")),
            initialdir=os.path.expanduser("~/Desktop/database_backups")
        )
        if file_path:
            filename = os.path.basename(file_path)
            if messagebox.askyesno("Confirm Restore", f"Are you sure you want to restore from:\n{filename}\n\nWARNING: Current database data will be overwritten!"):
                # Use single quotes for path to handle spaces
                self._exec_command_with_terminal(["restore", f"'{file_path}'"], hold=True)

    def _server_action(self, action, process=None):
        """Execute server management actions"""
        if action == "start_all":
            self._exec_command_with_terminal(["start"])
        elif action == "stop_all":
            self._exec_command_with_terminal(["stop"])
        elif action == "backup":
            self._exec_command_with_terminal(["backup"])
        # --- UPDATE: Added backup_silent ---
        elif action == "backup_silent":
            self._exec_command(["backup_silent"])
        elif action == "patch":
            self._exec_command_with_terminal(["patch"], hold=True)
        elif action == "backup_server":
            self._exec_command_with_terminal(["patch"], hold=True)  # Will show menu with backup option
        elif action == "start" and process:
            self._exec_command_with_terminal(["start", process.replace("_y", "")])
        elif action == "stop" and process:
            self._exec_command_with_terminal(["stop", process.replace("_y", "")])
    
    def _open_users_manager(self):
        # Lấy đường dẫn tuyệt đối của file users.py cùng thư mục với file app.py hiện tại
        current_dir = os.path.dirname(os.path.abspath(__file__))
        users_script = os.path.join(current_dir, "users.py")
        
        # Kiểm tra file có tồn tại không trước khi mở
        if not os.path.exists(users_script):
            messagebox.showerror("Lỗi", f"Không tìm thấy file: {users_script}")
            return

        try:
            # Sử dụng sys.executable để lấy chính xác trình thông dịch python đang chạy app này
            import sys
            subprocess.Popen([sys.executable, users_script], 
                             cwd=current_dir, # Chạy tại thư mục gốc của nó
                             start_new_session=True) # Tách biệt tiến trình hoàn toàn
        except Exception as e:
            messagebox.showerror("Lỗi hệ thống", f"Lỗi khi khởi chạy Tài Khoản: {str(e)}")

    def _exec_command(self, args):
        """Execute jx_new.sh command"""
        if not os.path.exists(self.BASH_SCRIPT):
            messagebox.showerror("Error", f"Script not found: {self.BASH_SCRIPT}")
            return
            
        env = os.environ.copy()
        env["GAMEPATH"] = self.server_config["directory"]
        env["SERVER_IP"] = self.server_config.get("server_ip", "")
        env["SERVER_MAC"] = self.server_config.get("server_mac", "")
        
        try:
            subprocess.Popen(['bash', self.BASH_SCRIPT] + args, env=env)
        except Exception as e:
            logging.error(f"Error executing command: {e}")
            messagebox.showerror("Error", f"Failed to execute command: {e}")

    def _exec_command_with_terminal(self, args, hold=False):
        """Execute command in terminal window"""
        if not os.path.exists(self.BASH_SCRIPT):
            messagebox.showerror("Error", f"Script not found: {self.BASH_SCRIPT}")
            return
            
        env = os.environ.copy()
        env["GAMEPATH"] = self.server_config["directory"]
        env["SERVER_IP"] = self.server_config.get("server_ip", "")
        env["SERVER_MAC"] = self.server_config.get("server_mac", "")
        
        try:
            cmd_args = ['xfce4-terminal', '--command', 'bash -c "{} {}"'.format(self.BASH_SCRIPT, ' '.join(args))]
            if hold:
                cmd_args = ['xfce4-terminal', '--hold', '--command', 'bash -c "{} {}"'.format(self.BASH_SCRIPT, ' '.join(args))]
            
            subprocess.Popen(cmd_args, env=env)
        except Exception as e:
            logging.error(f"Error executing terminal command: {e}")
            messagebox.showerror("Error", f"Failed to execute command: {e}")

    def _check_process_status(self, process_name):
        """Check if a process is running"""
        search_name = process_name
        if process_name == "MSSQL":
            search_name = "/opt/mssql/bin/sqlservr"
        elif process_name == "MySQL":
            search_name = "mysqld"
        elif process_name == "PaySys":
            search_name = "Sword3PaySys.exe"
        elif process_name == "RelayServer":
            search_name = "S3RelayServer.exe"
        
        try:
            output = subprocess.check_output(['pgrep', '-f', search_name])
            return bool(output)
        except subprocess.CalledProcessError:
            return False

    def _start_server_monitoring(self):
        """Start monitoring server processes"""
        def monitor():
            while True:
                # Check all processes
                for process_name in self.processes:
                    status = self._check_process_status(process_name)
                    self.processes[process_name]["status"] = status
                    if process_name in self.server_ui:
                        text = "Running" if status else "Stopped"
                        color = "green" if status else "red"
                        self.server_ui[process_name]["status_label"].config(text=text, fg=color)
                
                # Check hidden processes
                for process_name in self.hidden_processes:
                    status = self._check_process_status(process_name)
                    self.hidden_processes[process_name]["status"] = status
                    if process_name in self.server_ui:
                        text = "Running" if status else "Stopped"
                        color = "green" if status else "red"
                        self.server_ui[process_name]["status_label"].config(text=text, fg=color)
                
                time.sleep(2)
        
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

    def toggle_restart_options(self):
        mode = self.monitor_mode.get()
        if mode in ['scheduled', 'hybrid']:
            self.interval_spinbox.config(state=tk.NORMAL)
            self.delay_spinbox.config(state=tk.NORMAL)
        else:
            self.interval_spinbox.config(state=tk.DISABLED)
            self.delay_spinbox.config(state=tk.DISABLED)

    def browse_script(self):
        filename = filedialog.askopenfilename(
            title="Select a script", filetypes=(("Shell scripts", "*.sh"), ("All files", "*.*")))
        if filename:
            self.launch_script.set(filename)

    def start_monitoring(self):
        script = self.launch_script.get()
        proc_name = self.process_name.get()

        if not script or not proc_name:
            messagebox.showerror("Error", "Both script path and process name are required.")
            return

        if not os.path.exists(script):
            messagebox.showerror("Error", f"Script file not found:\n{script}")
            return
            
        try:
            check_proc = subprocess.run(['pidof', proc_name], capture_output=True, text=True)
            if check_proc.returncode == 0:
                pids = check_proc.stdout.strip()
                msg = (f"A process named '{proc_name}' is already running (PID(s): {pids}).\n\n"
                       "Do you want to take over monitoring this process?")
                if not messagebox.askyesno("Process Already Running", msg):
                    return
        except FileNotFoundError:
            self.handle_fatal_error("'pidof' command not found. Please install 'procps'.")
            return
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while checking for the process: {e}")
            return

        self.save_config()
        self.successful_restarts.set(0)
        self.failed_restarts.set(0)
        self.unexpected_shutdowns.set(0)
        self.monitoring.set()
        self.start_time = time.time()
        
        mode = self.monitor_mode.get()
        if mode == 'automatic':
            self.monitor_thread = threading.Thread(target=self.auto_restart_loop, daemon=True)
        elif mode == 'scheduled':
            self.monitor_thread = threading.Thread(target=self.scheduled_restart_loop, daemon=True)
        elif mode == 'hybrid':
            self.monitor_thread = threading.Thread(target=self.hybrid_restart_loop, daemon=True)
        
        self.monitor_thread.start()
        self.set_ui_state_active()
        
    def stop_monitoring(self):
        if self.monitoring.is_set():
            self.monitoring.clear()
            proc_name = self.process_name.get()
            if proc_name:
                try:
                    pid_proc = subprocess.run(['pidof', proc_name], capture_output=True, text=True)
                    if pid_proc.returncode == 0:
                        pids = pid_proc.stdout.strip().split()
                        for pid in pids:
                            logging.info(f"Stopping: Killing process '{proc_name}' (PID: {pid}).")
                            subprocess.run(['kill', '-9', pid])
                except Exception as e:
                    logging.error(f"Error while trying to kill process on stop: {e}")
            
            if self.monitor_thread and self.monitor_thread.is_alive():
                 self.monitor_thread.join(timeout=2)

            if self.start_time:
                self.last_runtime_seconds = time.time() - self.start_time
            self.start_time = None
            self.set_ui_state_idle()
            logging.info("Monitoring stopped by user.")

    def _start_process(self, script_path, proc_name, script_dir):
        """Helper function to start the process and handle success/failure."""
        try:
            self.process = subprocess.Popen(
                ['/bin/bash', script_path], cwd=script_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            time.sleep(1) 
            check_proc = subprocess.run(['pidof', proc_name], capture_output=True)
            if check_proc.returncode == 0:
                self.successful_restarts.set(self.successful_restarts.get() + 1)
                logging.info(f"Successfully started '{script_path}' with PID: {self.process.pid}")
                return True
            else:
                raise RuntimeError("Process failed to start or exited immediately.")
        except Exception as e:
            self.failed_restarts.set(self.failed_restarts.get() + 1)
            logging.error(f"Failed to start process '{proc_name}': {e}")
            return False

    def auto_restart_loop(self):
        script_path = self.launch_script.get()
        proc_name = self.process_name.get()
        script_dir = os.path.dirname(script_path)

        while self.monitoring.is_set():
            try:
                check_proc = subprocess.run(['pidof', proc_name], capture_output=True)
                if check_proc.returncode != 0:
                    logging.info(f"Process '{proc_name}' not found. Restarting...")
                    self._start_process(script_path, proc_name, script_dir)
            except Exception as e:
                logging.error(f"An error occurred in the auto-restart loop: {e}")
            time.sleep(self.check_interval)

    def scheduled_restart_loop(self):
        interval_seconds = int(self.restart_interval.get()) * 60
        while self.monitoring.is_set():
            for _ in range(interval_seconds):
                if not self.monitoring.is_set(): break
                time.sleep(1)
            if not self.monitoring.is_set(): break
            self._perform_scheduled_restart()

    def hybrid_restart_loop(self):
        interval_seconds = int(self.restart_interval.get()) * 60
        script_path = self.launch_script.get()
        proc_name = self.process_name.get()
        script_dir = os.path.dirname(script_path)

        while self.monitoring.is_set():
            next_scheduled_restart_time = time.time() + interval_seconds

            while time.time() < next_scheduled_restart_time:
                if not self.monitoring.is_set(): break
                try:
                    check_proc = subprocess.run(['pidof', proc_name], capture_output=True)
                    if check_proc.returncode != 0:
                        logging.info(f"HYBRID: Process '{proc_name}' failed. Performing auto-recovery.")
                        self.unexpected_shutdowns.set(self.unexpected_shutdowns.get() + 1)
                        
                        if self._start_process(script_path, proc_name, script_dir):
                            logging.info("HYBRID: Auto-recovery successful. Resetting scheduled timer.")
                            break
                        else:
                             logging.error("HYBRID: Auto-recovery failed. Will retry after check interval.")
                except Exception as e:
                    logging.error(f"HYBRID: An error occurred during health check: {e}")
                
                wait_time = min(self.check_interval, next_scheduled_restart_time - time.time())
                if wait_time > 0:
                    time.sleep(wait_time)

            if not self.monitoring.is_set(): break
            
            if time.time() >= next_scheduled_restart_time:
                logging.info(f"HYBRID: Scheduled interval reached. Performing planned restart.")
                self._perform_scheduled_restart()

    def _perform_scheduled_restart(self):
        proc_name = self.process_name.get()
        script_path = self.launch_script.get()
        script_dir = os.path.dirname(script_path)
        delay_seconds = int(self.restart_delay.get())

        if self.start_time is not None:
            self.last_runtime_seconds = time.time() - self.start_time

        try:
            pid_proc = subprocess.run(['pidof', proc_name], capture_output=True, text=True)
            if pid_proc.returncode == 0:
                pids = pid_proc.stdout.strip().split()
                for pid in pids:
                    logging.info(f"Scheduled stop: Killing existing process '{proc_name}' (PID: {pid}).")
                    subprocess.run(['kill', '-9', pid])
                logging.info(f"Waiting for {delay_seconds} seconds before restarting...")
                time.sleep(delay_seconds)
        except Exception as e:
            logging.error(f"Error killing process for scheduled restart: {e}")
        
        if not self.monitoring.is_set(): return

        logging.info(f"Scheduled restart: Starting new process instance '{proc_name}'.")
        if self._start_process(script_path, proc_name, script_dir):
            self.start_time = time.time()
        else:
            self.root.after(0, self.handle_fatal_error, "Failed to restart the process on schedule.")

    def handle_fatal_error(self, message):
        self.monitoring.clear()
        messagebox.showerror("Fatal Error", message)
        self.set_ui_state_idle()

    def _set_widget_state(self, parent_widget, state):
        for widget in parent_widget.winfo_children():
            try:
                widget.config(state=state)
            except tk.TclError:
                pass
            self._set_widget_state(widget, state)

    def set_ui_state_active(self):
        self.status_label.config(text="ACTIVE", fg="green")
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.script_entry.config(state=tk.DISABLED)
        self.process_entry.config(state=tk.DISABLED)
        self._set_widget_state(self.start_options_frame, tk.DISABLED)

    def set_ui_state_idle(self):
        self.status_label.config(text="IDLE", fg="red")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.script_entry.config(state=tk.NORMAL)
        self.process_entry.config(state=tk.NORMAL)
        self._set_widget_state(self.start_options_frame, tk.NORMAL)
        self.toggle_restart_options()
        self.current_runtime_str.set("00:00:00")

    def update_runtime_display(self):
        if self.start_time:
            elapsed = time.time() - self.start_time
            self.current_runtime_str.set(str(timedelta(seconds=int(elapsed))))
        
        self.last_runtime_str.set(str(timedelta(seconds=int(self.last_runtime_seconds))))
        
        # Update current time label in schedule section
        if hasattr(self, 'schedule_current_time_label'):
            now = datetime.now()
            time_12hr = now.strftime("%I:%M:%S %p")
            self.schedule_current_time_label.config(text=f"Now: {time_12hr}")
        
        self.root.after(1000, self.update_runtime_display)

    def view_log(self):
        log_window = tk.Toplevel(self.root)
        log_window.title("Log Viewer")
        log_window.geometry("800x600")
        log_text = scrolledtext.ScrolledText(log_window, state='disabled', wrap=tk.WORD)
        log_text.pack(expand=True, fill='both')

        try:
            with open(self.log_file, 'r') as f:
                log_content = f.read()
                log_text.config(state='normal')
                log_text.insert(tk.END, log_content)
                log_text.config(state='disabled')
                log_text.see(tk.END)
        except FileNotFoundError:
            log_text.config(state='normal')
            log_text.insert(tk.END, "Log file not found.")
            log_text.config(state='disabled')

    # ========== Scheduling Methods ==========
    
    def load_scheduled_tasks(self):
        """Load scheduled tasks from config"""
        schedule_file = os.path.join(os.path.expanduser("~"), ".server_schedule.json")
        try:
            if os.path.exists(schedule_file):
                with open(schedule_file, 'r') as f:
                    self.scheduled_tasks = json.load(f)
                    logging.info(f"Loaded {len(self.scheduled_tasks)} scheduled tasks.")
        except Exception as e:
            logging.error(f"Failed to load scheduled tasks: {e}")
            self.scheduled_tasks = []

    def save_scheduled_tasks(self):
        """Save scheduled tasks to config"""
        schedule_file = os.path.join(os.path.expanduser("~"), ".server_schedule.json")
        try:
            with open(schedule_file, 'w') as f:
                json.dump(self.scheduled_tasks, f, indent=4)
                logging.info("Scheduled tasks saved.")
        except Exception as e:
            logging.error(f"Failed to save scheduled tasks: {e}")

    def _add_schedule(self):
        """Add a new scheduled task"""
        try:
            hour_12 = int(self.schedule_hour.get())
            minute = int(self.schedule_minute.get())
            ampm = self.schedule_ampm.get()
            action_text = self.schedule_action.get()
            
            # Validate time
            if not (1 <= hour_12 <= 12 and 0 <= minute <= 59):
                messagebox.showerror("Error", "Invalid time. Hour must be 1-12, minute must be 0-59.")
                return
            
            # Convert to 24-hour format
            if ampm == "AM":
                hour_24 = hour_12 if hour_12 != 12 else 0
            else:  # PM
                hour_24 = hour_12 if hour_12 == 12 else hour_12 + 12
            
            time_str = f"{hour_24:02d}:{minute:02d}"
            action = "start_all" if action_text == "Start All" else "stop_all"
            if action_text == "Backup": action = "backup"
            
            # Check if this exact time+action already exists
            for task in self.scheduled_tasks:
                if task['time'] == time_str and task['action'] == action:
                    messagebox.showwarning("Warning", f"Schedule for {time_str} - {action_text} already exists.")
                    return
            
            # Add new task
            new_task = {
                "time": time_str,
                "action": action,
                "enabled": True,
                "executed_today": False
            }
            self.scheduled_tasks.append(new_task)
            
            # Sort by time
            self.scheduled_tasks.sort(key=lambda x: x['time'])
            
            self.save_scheduled_tasks()
            self._refresh_schedule_list()
            
            logging.info(f"Added schedule: {time_str} - {action_text}")
            messagebox.showinfo("Success", f"Schedule added: {time_str} - {action_text}")
            
        except ValueError:
            messagebox.showerror("Error", "Invalid time format.")

    def _remove_schedule(self):
        """Remove selected scheduled task"""
        try:
            selection = self.schedule_listbox.curselection()
            if not selection:
                messagebox.showwarning("Warning", "Please select a schedule to remove.")
                return
            
            index = selection[0]
            removed_task = self.scheduled_tasks.pop(index)
            
            self.save_scheduled_tasks()
            self._refresh_schedule_list()
            
            logging.info(f"Removed schedule: {removed_task['time']} - {removed_task['action']}")
            messagebox.showinfo("Success", "Schedule removed.")
            
        except Exception as e:
            logging.error(f"Error removing schedule: {e}")
            messagebox.showerror("Error", f"Failed to remove schedule: {e}")

    def _clear_schedules(self):
        """Clear all scheduled tasks"""
        if not self.scheduled_tasks:
            messagebox.showinfo("Info", "No schedules to clear.")
            return
        
        if messagebox.askyesno("Confirm", "Are you sure you want to remove all schedules?"):
            self.scheduled_tasks = []
            self.save_scheduled_tasks()
            self._refresh_schedule_list()
            logging.info("All schedules cleared.")
            messagebox.showinfo("Success", "All schedules cleared.")

    def _refresh_schedule_list(self):
        """Refresh the schedule listbox display"""
        self.schedule_listbox.delete(0, tk.END)
        
        for task in self.scheduled_tasks:
            # Convert 24-hour time to 12-hour format with AM/PM
            hour_24, minute = map(int, task['time'].split(':'))
            
            if hour_24 == 0:
                hour_12 = 12
                ampm = "AM"
            elif hour_24 < 12:
                hour_12 = hour_24
                ampm = "AM"
            elif hour_24 == 12:
                hour_12 = 12
                ampm = "PM"
            else:
                hour_12 = hour_24 - 12
                ampm = "PM"
            
            time_12hr = f"{hour_12:02d}:{minute:02d} {ampm}"
            action_map = {"start_all": "Start All", "stop_all": "Stop All", "backup": "Backup"}
            action_text = action_map.get(task['action'], task['action'])
            
            status = "✓" if task.get('executed_today', False) else "⏰"
            display_text = f"{status} {time_12hr} - {action_text}"
            self.schedule_listbox.insert(tk.END, display_text)

    def _start_schedule_monitoring(self):
        """Start monitoring scheduled tasks"""
        def monitor():
            last_check_date = datetime.now().date()
            logging.info("Schedule monitoring thread started.")
            
            while True:
                try:
                    current_time = datetime.now()
                    current_date = current_time.date()
                    current_time_str = current_time.strftime("%H:%M")
                    
                    # Log current check (only once per minute to avoid spam)
                    if current_time.second < 30:
                        logging.info(f"Schedule check: Current time {current_time_str}, Active schedules: {len(self.scheduled_tasks)}")
                    
                    # Reset executed_today flag if it's a new day
                    if current_date != last_check_date:
                        logging.info("New day detected. Resetting schedule execution flags.")
                        for task in self.scheduled_tasks:
                            task['executed_today'] = False
                        self.save_scheduled_tasks()
                        self.root.after(0, self._refresh_schedule_list)
                        last_check_date = current_date
                    
                    # Check each scheduled task
                    for task in self.scheduled_tasks:
                        if not task.get('enabled', True):
                            continue
                        
                        logging.debug(f"Checking schedule: {task['time']} vs current {current_time_str}, executed: {task.get('executed_today', False)}")
                        
                        if task['time'] == current_time_str and not task.get('executed_today', False):
                            # Execute the scheduled action
                            action = task['action']
                            logging.info(f"⏰ EXECUTING scheduled action: {action} at {current_time_str}")
                            
                            # Use default argument to capture action value correctly
                            if action == "start_all":
                                self.root.after(0, lambda a=action: self._server_action("start_all"))
                            elif action == "stop_all":
                                self.root.after(0, lambda a=action: self._server_action("stop_all"))
                            elif action == "backup":
                                self.root.after(0, lambda a=action: self._exec_command(["backup_silent"]))
                            
                            # Mark as executed today
                            task['executed_today'] = True
                            self.save_scheduled_tasks()
                            self.root.after(0, self._refresh_schedule_list)
                            logging.info(f"✓ Schedule executed and marked as complete")
                
                except Exception as e:
                    logging.error(f"Error in schedule monitoring: {e}")
                
                time.sleep(5)  # Check every 5 seconds
        
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        logging.info("Schedule monitoring started.")


if __name__ == "__main__":
    root = tk.Tk()
    app = ProcessRestarterApp(root)
    root.mainloop()
