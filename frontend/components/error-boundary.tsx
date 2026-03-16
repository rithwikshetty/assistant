
import { Component } from "react";
import type { ComponentType, FC, ReactNode } from "react";
import { Warning, ArrowsClockwise } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
  fallback?: ComponentType<ErrorFallbackProps>;
}

interface State {
  hasError: boolean;
  error?: Error;
}

interface ErrorFallbackProps {
  error?: Error;
  resetError: () => void;
}

const DefaultErrorFallback: FC<ErrorFallbackProps> = ({ error, resetError }) => (
  <div className="flex flex-col items-center justify-center p-8 text-center space-y-4">
    <Warning className="size-12 text-destructive" />
    <div className="space-y-2">
      <h2 className="type-size-20 font-semibold text-foreground">Something went wrong</h2>
      <p className="type-size-14 text-muted-foreground max-w-md">
        {error?.message || 'An unexpected error occurred. Please try again.'}
      </p>
    </div>
    <Button
      onClick={resetError}
      className="inline-flex items-center gap-2 px-4 py-2 type-size-14 font-medium text-background bg-foreground rounded-full hover:bg-foreground/90"
    >
      <ArrowsClockwise className="size-4" />
      Try again
    </Button>
  </div>
);

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  resetError = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      const FallbackComponent = this.props.fallback || DefaultErrorFallback;
      return (
        <FallbackComponent 
          error={this.state.error} 
          resetError={this.resetError}
        />
      );
    }

    return this.props.children;
  }
}

// Hook-based error boundary for functional components
export function useErrorHandler() {
  return (error: Error) => {
    // Manual error handler caught an error
    throw error; // Re-throw to trigger error boundary
  };
}
