import { Component } from "react";

// 페이지 렌더링 중 예외가 나도 앱 전체가 죽지 않도록 감싸는 경계 컴포넌트.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidUpdate(prevProps) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  retry = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <section className="page">
          <div className="panel error-boundary">
            <h2>화면을 표시하는 중 문제가 발생했습니다.</h2>
            <p className="alert">{String(this.state.error?.message || this.state.error)}</p>
            <button type="button" onClick={this.retry}>
              다시 시도
            </button>
          </div>
        </section>
      );
    }
    return this.props.children;
  }
}
