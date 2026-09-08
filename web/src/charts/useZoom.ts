/**
 * Drag to pan, wheel to zoom, double-click to reset — over a slot index window.
 *
 * The window is an index range rather than a date range because the x axis is categorical:
 * sessions are slots, and an absent settlement occupies one. A time scale would place a
 * missing Monday a weekend's width from its neighbour and leave the dashed column floating
 * where no session is.
 *
 * `scopeKey` is the chart's identity. When it changes the window resets to the returned
 * extent; while it holds, the window survives re-renders — which is what makes a family click
 * keep the zoom and a contract change drop it (`specs/loupe-ui-design.md`, Zoom and identity).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { clampExtent, IDENTITY, panExtent, zoomExtent, type Extent } from "./scale";

export interface Zoom {
  extent: Extent;
  reset: () => void;
  /** Spread onto the `<svg>`: drag, wheel and double-click handlers. */
  handlers: {
    onPointerDown: (event: React.PointerEvent<SVGSVGElement>) => void;
    onPointerMove: (event: React.PointerEvent<SVGSVGElement>) => void;
    onPointerUp: (event: React.PointerEvent<SVGSVGElement>) => void;
    onDoubleClick: () => void;
    onWheel: (event: React.WheelEvent<SVGSVGElement>) => void;
    style: React.CSSProperties;
  };
}

export function useZoom(count: number, scopeKey: string): Zoom {
  const [extent, setExtent] = useState<Extent>(() => IDENTITY(count));
  const identity = useRef({ key: scopeKey, count });
  const drag = useRef<{ x: number; start: Extent; width: number } | null>(null);

  useEffect(() => {
    if (identity.current.key === scopeKey && identity.current.count === count) return;
    identity.current = { key: scopeKey, count };
    setExtent(IDENTITY(count));
  }, [scopeKey, count]);

  const reset = useCallback(() => setExtent(IDENTITY(count)), [count]);

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    const width = event.currentTarget.getBoundingClientRect().width || 1;
    drag.current = { x: event.clientX, start: extent, width };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const held = drag.current;
    if (!held) return;
    const span = held.start.end - held.start.start;
    const slots = ((held.x - event.clientX) / held.width) * span;
    setExtent(panExtent(held.start, count, slots));
  };

  const onPointerUp = (event: React.PointerEvent<SVGSVGElement>) => {
    drag.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const onWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const focus = box.width ? (event.clientX - box.left) / box.width : 0.5;
    setExtent((current) =>
      zoomExtent(current, count, event.deltaY > 0 ? 1.2 : 1 / 1.2, focus),
    );
  };

  return {
    extent: clampExtent(extent, count),
    reset,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onDoubleClick: reset,
      onWheel,
      style: { touchAction: "none", cursor: "grab", display: "block", width: "100%" },
    },
  };
}
