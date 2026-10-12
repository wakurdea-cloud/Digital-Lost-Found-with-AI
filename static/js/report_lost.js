const imageInput = document.getElementById("imageInput");
const previewImage = document.getElementById("previewImage");
const uploadBox = document.querySelector(".upload-box");

// Image Preview
imageInput.addEventListener("change", function () {

    const file = this.files[0];

    if (!file) return;

    // Allow only images
    if (!file.type.startsWith("image/")) {
        alert("Please upload a valid image (JPG, PNG, JPEG).");
        imageInput.value = "";
        return;
    }

    const reader = new FileReader();

    reader.onload = function (e) {
        previewImage.src = e.target.result;
        previewImage.style.display = "block";
    };

    reader.readAsDataURL(file);

});

// Drag Over
uploadBox.addEventListener("dragover", function (e) {
    e.preventDefault();
    uploadBox.style.borderColor = "#22c55e";
});

// Drag Leave
uploadBox.addEventListener("dragleave", function () {
    uploadBox.style.borderColor = "#38bdf8";
});

// Drop Image
uploadBox.addEventListener("drop", function (e) {

    e.preventDefault();

    uploadBox.style.borderColor = "#38bdf8";

    const file = e.dataTransfer.files[0];

    if (!file) return;

    if (!file.type.startsWith("image/")) {
        alert("Only image files are allowed.");
        return;
    }

    imageInput.files = e.dataTransfer.files;

    const reader = new FileReader();

    reader.onload = function (event) {
        previewImage.src = event.target.result;
        previewImage.style.display = "block";
    };

    reader.readAsDataURL(file);

});


const descriptionInput = document.querySelector(
    'textarea[name="description"]'
);

function updateDescriptionRequirement() {

    if (imageInput.files.length === 0) {

        descriptionInput.required = true;

        descriptionInput
            .previousElementSibling
            .textContent = "Description (Required)";

    } else {

        descriptionInput.required = false;

        descriptionInput
            .previousElementSibling
            .textContent = "Description (Optional)";
    }
}

imageInput.addEventListener(
    "change",
    updateDescriptionRequirement
);

updateDescriptionRequirement();
