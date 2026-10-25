import { useEffect, useRef, useState } from "react";
import type { ModelCatalog } from "../../types";

type ModelPickerProps = {
  id: string;
  cloudModel: string;
  onChangeCloudModel: (modelId: string) => void;
  cloudModels: ModelCatalog;
};

/**
 * Custom (non-native) dropdown for the OpenRouter model list.
 *
 * A plain <select> here hit a real, reproducible bug on Linux/Chromium: with
 * a long, grouped option list (15+ free models + a paid group), the native
 * OS popup would open and immediately close on click, making the model
 * unselectable. This is a separate, worse case of the same class of native
 * <select> popup flakiness fixed for the short dropdowns elsewhere in this
 * file (see ChatModeSelector's label/select de-nesting fix) — long grouped
 * lists trigger it even without that bug. Rendering our own listbox sidesteps
 * the native OS popup entirely, so it can't happen regardless of the exact
 * underlying platform cause.
 */
export function ModelPicker({ id, cloudModel, onChangeCloudModel, cloudModels }: ModelPickerProps) {
  // ModelPicker: lets the user choose which cloud (OpenRouter) generating model answers
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isOpen]);

  const selectedLabel =
    [...cloudModels.free, ...cloudModels.paid].find((m) => m.id === cloudModel)?.name ?? "Select a model…";

  return (
    <div className="model-picker" ref={containerRef}>
      <button
        type="button"
        id={id}
        className="model-picker-trigger"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
      >
        {selectedLabel}
        <span aria-hidden="true">▾</span>
      </button>
      {isOpen && (
        <ul className="model-picker-list" role="listbox">
          <li className="model-picker-group-label">Free</li>
          {cloudModels.free.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                role="option"
                aria-selected={m.id === cloudModel}
                className={m.id === cloudModel ? "selected" : undefined}
                onClick={() => {
                  onChangeCloudModel(m.id);
                  setIsOpen(false);
                }}
              >
                {m.name}
              </button>
            </li>
          ))}
          {cloudModels.paid.length > 0 && (
            <>
              <li className="model-picker-group-label">Paid (not selectable in this learning app)</li>
              {cloudModels.paid.map((m) => (
                <li key={m.id}>
                  <button type="button" role="option" disabled className="paid-option">
                    {m.name}
                  </button>
                </li>
              ))}
            </>
          )}
        </ul>
      )}
    </div>
  );
}
