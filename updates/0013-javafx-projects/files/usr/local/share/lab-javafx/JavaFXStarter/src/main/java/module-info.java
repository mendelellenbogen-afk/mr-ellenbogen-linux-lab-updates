module com.example.javafxstarter {
    requires javafx.controls;
    requires javafx.fxml;

    opens com.example.javafxstarter to javafx.fxml;
    exports com.example.javafxstarter;
}

