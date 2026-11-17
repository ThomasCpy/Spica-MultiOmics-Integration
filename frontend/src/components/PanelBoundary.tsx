import { Component, type ReactNode } from "react";

// A panel that fails says so and stays a panel. Without a boundary, an
// error thrown while rendering, or in an effect (a third-party viewer
// misbehaving), unmounts the whole interface and leaves a blank window.

type Props = { name: string; children: ReactNode };
type State = { error: string };

export class PanelBoundary extends Component<Props, State> {
  state: State = { error: "" };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error.message : String(error) };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="px-5 py-4 text-[13px] text-slate">
        The {this.props.name} stopped on an error and was closed so the rest keeps working: {this.state.error}.{" "}
        <button type="button" onClick={() => this.setState({ error: "" })} className="text-azure-deep hover:underline">
          Open it again
        </button>
      </div>
    );
  }
}
