import psutil
import os
from prometheus_client import Gauge, CollectorRegistry
from typing import Optional

try:
    import pynvml

    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except (ImportError, pynvml.NVMLError):
    NVML_AVAILABLE = False


class SystemMetricsCollector:
    def __init__(self, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or CollectorRegistry()

        # Gauges (point-in-time — no accumulation)
        self.process_cpu_percent = Gauge(
            "process_cpu_percent",
            "Current process CPU usage (%)",
            registry=self.registry,
        )
        self.process_memory_bytes = Gauge(
            "process_memory_bytes",
            "Current process memory RSS (bytes)",
            registry=self.registry,
        )
        self.system_cpu_percent = Gauge(
            "system_cpu_percent", "System-wide CPU usage (%)", registry=self.registry
        )
        self.system_memory_percent = Gauge(
            "system_memory_percent",
            "System-wide memory usage (%)",
            registry=self.registry,
        )
        self.system_memory_available_bytes = Gauge(
            "system_memory_available_bytes",
            "System memory available (bytes)",
            registry=self.registry,
        )
        self.disk_usage_percent = Gauge(
            "disk_usage_percent",
            "Disk usage percent for app volume",
            registry=self.registry,
        )
        self.disk_free_bytes = Gauge(
            "disk_free_bytes", "Disk free space (bytes)", registry=self.registry
        )

        if NVML_AVAILABLE:
            self.gpu_utilization = Gauge(
                "gpu_utilization_percent",
                "GPU utilization (%)",
                ["device"],
                registry=self.registry,
            )
            self.gpu_memory_used_bytes = Gauge(
                "gpu_memory_used_bytes",
                "GPU memory used (bytes)",
                ["device"],
                registry=self.registry,
            )
            self.gpu_memory_total_bytes = Gauge(
                "gpu_memory_total_bytes",
                "GPU memory total (bytes)",
                ["device"],
                registry=self.registry,
            )

        # Register self for periodic collection
        self.collect()

    def collect(self):
        # Process metrics
        proc = psutil.Process(os.getpid())
        self.process_cpu_percent.set(proc.cpu_percent(interval=0.1))
        self.process_memory_bytes.set(proc.memory_info().rss)

        # System metrics
        self.system_cpu_percent.set(psutil.cpu_percent(interval=0.1))
        mem = psutil.virtual_memory()
        self.system_memory_percent.set(mem.percent)
        self.system_memory_available_bytes.set(mem.available)

        # Disk (use app directory’s mount point)
        disk = psutil.disk_usage("/")
        self.disk_usage_percent.set(disk.percent)
        self.disk_free_bytes.set(disk.free)

        # GPU
        if NVML_AVAILABLE:
            try:
                device_count = pynvml.nvmlDeviceGetCount()
                for i in range(device_count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    self.gpu_utilization.labels(device=str(i)).set(util.gpu)
                    self.gpu_memory_used_bytes.labels(device=str(i)).set(mem_info.used)
                    self.gpu_memory_total_bytes.labels(device=str(i)).set(
                        mem_info.total
                    )
            except pynvml.NVMLError:
                pass

        return []
