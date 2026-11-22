// Author: Ching Kao
// Student ID: 85768427
/** Geometry and input handling shared by movable/resizable tool panels. */
export function createFloatingPanel({
  panel,
  header,
  handle,
  resize,
  top: initialTop,
  announce,
}: {
  panel: HTMLElement;
  header: HTMLElement;
  handle: HTMLButtonElement;
  resize: HTMLButtonElement;
  top: () => number;
  announce: (message: string) => void;
}) {
  let collapsed = false,
    width = 358,
    height = 468;
  let left = Math.max(8, innerWidth - width - 24),
    top = initialTop();
  function layout() {
    const maxWidth = Math.max(1, window.innerWidth - 16),
      maxHeight = Math.max(1, window.innerHeight - 16);
    width = Math.min(Math.max(Math.min(300, maxWidth), width), maxWidth);
    height = Math.min(Math.max(Math.min(340, maxHeight), height), maxHeight);
    const visibleWidth = width;
    left = Math.max(8, Math.min(left, window.innerWidth - visibleWidth - 8));
    top = Math.max(
      8,
      Math.min(top, window.innerHeight - (collapsed ? 40 : height) - 8),
    );
    Object.assign(panel.style, {
      left: `${left}px`,
      top: `${top}px`,
      width: `${visibleWidth}px`,
      height: `${collapsed ? 40 : height}px`,
    });
  }
  function pointerControl(control: HTMLElement, resizing: boolean) {
    let startX = 0,
      startY = 0,
      startLeft = 0,
      startTop = 0,
      startWidth = 0,
      startHeight = 0;
    control.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !event.isPrimary) return;
      const interactive = (event.target as Element).closest(
        "button, input, select, textarea, a",
      );
      if (interactive && interactive !== handle && interactive !== control)
        return;
      startX = event.clientX;
      startY = event.clientY;
      startLeft = left;
      startTop = top;
      startWidth = width;
      startHeight = height;
      control.setPointerCapture(event.pointerId);
      document.body.classList.add("moving-panel");
      control.classList.add("dragging");
    });
    control.addEventListener("pointermove", (event) => {
      if (!control.hasPointerCapture(event.pointerId)) return;
      if (resizing) {
        width = Math.min(
          startWidth + event.clientX - startX,
          window.innerWidth - left - 8,
        );
        height = Math.min(
          startHeight + event.clientY - startY,
          window.innerHeight - top - 8,
        );
      } else {
        left = startLeft + event.clientX - startX;
        top = startTop + event.clientY - startY;
      }
      layout();
    });
    const finish = () => {
      document.body.classList.remove("moving-panel");
      control.classList.remove("dragging");
      announce(resizing ? "Panel resized." : "Panel moved.");
    };
    control.addEventListener("pointerup", (event) => {
      if (control.hasPointerCapture(event.pointerId))
        control.releasePointerCapture(event.pointerId);
    });
    control.addEventListener("pointercancel", finish);
    control.addEventListener("lostpointercapture", finish);
    control.addEventListener("keydown", (event) => {
      if (event.target !== handle && event.target !== control) return;
      const moves: Record<string, [number, number]> = {
        ArrowLeft: [-16, 0],
        ArrowRight: [16, 0],
        ArrowUp: [0, -16],
        ArrowDown: [0, 16],
      };
      const move = moves[event.key];
      if (!move) return;
      event.preventDefault();
      if (resizing) {
        width += move[0];
        height += move[1];
      } else {
        left += move[0];
        top += move[1];
      }
      layout();
      finish();
    });
  }
  pointerControl(header, false);
  pointerControl(resize, true);
  window.addEventListener("resize", layout);
  layout();
  return {
    setCollapsed(value: boolean) {
      collapsed = value;
      layout();
    },
  };
}
