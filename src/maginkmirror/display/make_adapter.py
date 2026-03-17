from maginkmirror.display.base_display_adapter import BaseDisplayAdapter, HeadlessAdapter, WaveshareAdapter
from maginkmirror.display.inky_impression_adapter import InkyImpressionAdapter

def make_adapter(config: dict) -> BaseDisplayAdapter:
    """Create a display adapter based on the configuration."""
    driver = config.get("display", {}).get("driver", "headless")
    if driver == "headless":
        out = config.get("display", {}).get("output_dir", "/tmp/maginkmirror_output")
        return HeadlessAdapter(output_dir=out)
    elif driver == "waveshare":
        model = config.get("display", {}).get("model", "epd7in5_V2")
        return WaveshareAdapter(model=model)
    elif driver == "inky":
        model = config.get("display", {}).get("model", "auto")
        return InkyImpressionAdapter(model=model)
    else:
        raise ValueError(f"Unknown display driver: {driver!r}")
