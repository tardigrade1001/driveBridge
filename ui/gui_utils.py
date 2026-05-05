def apply_window_icon(root):
    try:
        import os
        from pathlib import Path
        from PIL import Image, ImageDraw

        ico_path = str(Path(__file__).parent.parent / "drivebridge.ico")

        from core import config
        custom_icon = config.load_config().get("custom_icon_path", "")
        if custom_icon and os.path.exists(custom_icon):
            root.iconbitmap(custom_icon)
            return

        if not os.path.exists(ico_path):
            img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            color = "#7c6af7" # DriveBridge Accent
            # Left Cloud
            draw.ellipse((4,  30, 24, 48), fill=color)
            draw.ellipse((8,  20, 28, 42), fill=color)
            draw.ellipse((14, 32, 30, 50), fill=color)
            # Right Cloud
            draw.ellipse((34, 32, 50, 50), fill=color)
            draw.ellipse((36, 20, 56, 42), fill=color)
            draw.ellipse((40, 30, 60, 48), fill=color)

            # Wooden bridge connecting them
            wood_dark = "#5c3a21"
            wood_lite = "#8b5a2b"

            # Bridge deck
            draw.line((18, 38, 46, 38), fill=wood_dark, width=5)
            # Handrail
            draw.line((20, 30, 44, 30), fill=wood_lite, width=3)
            # Vertical Posts
            for x in (22, 28, 34, 40):
                draw.line((x, 30, x, 36), fill=wood_lite, width=2)

            img.save(ico_path, format="ICO", sizes=[(64, 64)])

        root.iconbitmap(ico_path)
    except Exception as e:
        pass
