## Frontend Development Standards

### 1. HTML & Embedded Content
- **In-file Indentation**: CSS within `<style>` and JS within `<script>` tags must follow the 2-space indentation rule, matching the parent HTML structure.
- **Separation of Concerns**: Favor external files over embedded styles/scripts unless the project is a single-file prototype.

### 2. UI/UX Design Principles
- **Design Philosophy**: Apply a **Flat Design** aesthetic—minimize gradients, shadows, and 3D effects. Focus on clarity and typography.
- **Typography**: 
    - Use **Pretendard Variable** as the primary typeface.
    - **Implementation**: Prefer CDN (e.g., `https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css`) for faster delivery.
    - **CSS Rule**: Set `font-family: "Pretendard Variable", ...;` in the root or body.
- **Responsiveness**: All UI components must be Mobile-First and responsive by default.

### 3. CSS/Styling
- **Naming Convention**: Use BEM (Block Element Modifier) or as defined in the project.
- **Modern CSS**: Prefer Flexbox and CSS Grid for layouts.
