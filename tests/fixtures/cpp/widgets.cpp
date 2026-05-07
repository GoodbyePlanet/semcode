#include <string>

namespace ui::widgets {

/** A clickable button. */
class Button {
public:
    Button();
    ~Button();

    /** Render the widget. */
    void render(int x, int y);
    static int defaultWidth();

private:
    int width_;
    std::string label_;
};

template<typename T>
class Container {
public:
    void add(T item) {}
};

int helper() { return 0; }

} // namespace ui::widgets

namespace other {
class Inner {};
}
