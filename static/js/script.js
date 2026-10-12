const counters=document.querySelectorAll(".counter");

counters.forEach(counter=>{

let target=+counter.dataset.target;
let count=0;

let update=()=>{

count+=Math.ceil(target/100);

if(count>=target){

counter.innerText=target;

}else{

counter.innerText=count;

requestAnimationFrame(update);

}

}

update();

});